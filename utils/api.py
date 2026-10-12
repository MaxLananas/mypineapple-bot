"""HTTP helpers for the Discord REST API.

Provides:
- ``api_send`` / ``api_edit`` / ``api_send_file`` with **exponential backoff**
  on 429/5xx and a small global rate limiter to respect Discord's limits.
- ``api_send_queued`` : fire-and-forget delivery through a background worker,
  used for bursty log traffic (avoids hammering the API).
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import aiohttp

log = logging.getLogger(__name__)


def _json_dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)

_session: aiohttp.ClientSession | None = None

NO_MENTIONS = {
    "parse":        [],
    "roles":        [],
    "users":        [],
    "replied_user": False,
}

# For messages that MUST ping (announcements…).
MENTIONS_ALL = {
    "parse":        ["users", "roles", "everyone"],
    "replied_user": True,
}

# ── Rate limiting ────────────────────────────────────────────────────────────
# Deux étages, parce qu'un seul limiteur global ne suffit pas :
#   1. **Par salon** (bucket Discord ≈ 5 messages / 5 s) : chaque salon a son
#      propre token-bucket + un verrou, donc deux coroutines ne peuvent pas
#      « tirer en même temps » sur le même salon. C'était la cause des
#      tempêtes de 429 : 30 logs envoyés en parallèle sur un même salon.
#   2. **Global** : plafond large pour ne pas exploser la limite du bot entier.
# Les 429 restants sont comptés et résumés en UNE ligne (au lieu d'une par
# tentative), pour ne pas noyer les logs de l'hôte.
_PER_CHANNEL_LIMIT  = 4         # envois max par fenêtre (Discord : 5 / 5 s)
_PER_CHANNEL_WINDOW = 5.0       # secondes
_GLOBAL_CAPACITY    = 30.0      # rafale globale
_GLOBAL_REFILL      = 20.0      # jetons/seconde (toutes routes confondues)


class _WindowLimiter:
    """Limiteur à **fenêtre glissante** : jamais plus de ``limit`` envois par
    ``window`` secondes. Plus sûr qu'un token-bucket (dont la rafale + le débit
    se cumulent) : on reste toujours sous la limite Discord du salon."""

    __slots__ = ("limit", "window", "sends", "lock", "blocked_until")

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self.sends: list[float] = []
        self.lock = asyncio.Lock()
        self.blocked_until = 0.0

    async def acquire(self) -> float:
        async with self.lock:
            waited = 0.0
            while True:
                now = time.monotonic()
                while self.sends and now - self.sends[0] >= self.window:
                    self.sends.pop(0)
                if now < self.blocked_until:
                    wait = self.blocked_until - now
                elif len(self.sends) >= self.limit:
                    wait = self.window - (now - self.sends[0]) + 0.05
                else:
                    self.sends.append(time.monotonic())
                    return waited
                await asyncio.sleep(wait)
                waited += wait

    def penalize(self, seconds: float) -> None:
        """429 : on repousse la fenêtre au lieu de réessayer immédiatement."""
        self.blocked_until = max(self.blocked_until, time.monotonic() + max(0.0, seconds))
        self.sends.clear()

    def current(self) -> int:
        now = time.monotonic()
        self.sends = [t for t in self.sends if now - t < self.window]
        return len(self.sends)


class _TokenBucket:
    """Token-bucket minimaliste (thread-safe via asyncio)."""

    __slots__ = ("capacity", "refill", "tokens", "updated", "lock", "blocked_until")

    def __init__(self, capacity: float, refill: float):
        self.capacity = capacity
        self.refill = refill
        self.tokens = capacity
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()
        self.blocked_until = 0.0

    def _regen(self, now: float) -> None:
        elapsed = now - self.updated
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill)
            self.updated = now

    async def acquire(self) -> float:
        """Consomme un jeton ; renvoie le temps d'attente imposé (0 si immédiat)."""
        async with self.lock:
            waited = 0.0
            while True:
                now = time.monotonic()
                self._regen(now)
                wait = 0.0
                if now < self.blocked_until:
                    wait = self.blocked_until - now
                if self.tokens < 1.0:
                    wait = max(wait, (1.0 - self.tokens) / self.refill)
                if wait <= 0:
                    self.tokens -= 1.0
                    return waited
                await asyncio.sleep(wait)
                waited += wait

    def penalize(self, seconds: float) -> None:
        """Un 429 impose un délai : on bloque le bucket au lieu de réessayer tout de suite."""
        self.blocked_until = max(self.blocked_until, time.monotonic() + max(0.0, seconds))
        self.tokens = 0.0
        self.updated = time.monotonic()


_GLOBAL_BUCKET = _TokenBucket(_GLOBAL_CAPACITY, _GLOBAL_REFILL)
_CHANNEL_LIMITERS: dict[int, _WindowLimiter] = {}


def _channel_limiter(channel_id: int) -> _WindowLimiter:
    limiter = _CHANNEL_LIMITERS.get(channel_id)
    if limiter is None:
        limiter = _WindowLimiter(_PER_CHANNEL_LIMIT, _PER_CHANNEL_WINDOW)
        _CHANNEL_LIMITERS[channel_id] = limiter
        if len(_CHANNEL_LIMITERS) > 500:     # nettoyage : on garde les plus récents
            for cid in list(_CHANNEL_LIMITERS)[:100]:
                _CHANNEL_LIMITERS.pop(cid, None)
    return limiter


def _channel_id_from_url(url: str) -> int:
    """Extrait l'ID de salon d'une URL Discord (0 si absent)."""
    try:
        parts = url.split("/")
        idx = parts.index("channels")
        return int(parts[idx + 1])
    except (ValueError, IndexError):
        return 0


async def _throttle(channel_id: int = 0) -> None:
    """Attend que le quota global **et** celui du salon permettent l'envoi."""
    await _GLOBAL_BUCKET.acquire()
    if channel_id:
        await _channel_limiter(channel_id).acquire()


# ── Journal des 429 (agrégé) ─────────────────────────────────────────────────
# Sans agrégation, une tempête de 429 écrivait des centaines de lignes
# « Rate limited, retrying in 1.07s » et noyait tout le reste. On compte et on
# résume : une ligne par fenêtre de _RL_REPORT_SECONDS, avec les salons touchés.
_RL_REPORT_SECONDS = 60.0
_rl_lock = asyncio.Lock()
_rl_count = 0
_rl_channels: dict[int, int] = {}
_rl_total_wait = 0.0
_rl_max_wait = 0.0
_rl_global = 0
_rl_since = 0.0
_rl_task: asyncio.Task | None = None


def _rl_note(channel_id: int, wait: float, *, is_global: bool = False) -> None:
    """Compte un 429 et publie un résumé au plus une fois par minute."""
    global _rl_count, _rl_total_wait, _rl_max_wait, _rl_global, _rl_since, _rl_task
    _rl_count += 1
    _rl_total_wait += wait
    _rl_max_wait = max(_rl_max_wait, wait)
    _rl_channels[channel_id] = _rl_channels.get(channel_id, 0) + 1
    if is_global:
        _rl_global += 1
    if _rl_since == 0.0:
        _rl_since = time.monotonic()
    if _rl_task is None or _rl_task.done():
        try:
            _rl_task = asyncio.get_running_loop().create_task(_rl_report_later())
        except RuntimeError:
            _rl_task = None


async def _rl_report_later() -> None:
    """Attend la fin de la fenêtre puis écrit le résumé (et remet les compteurs à zéro)."""
    global _rl_count, _rl_channels, _rl_total_wait, _rl_max_wait, _rl_global, _rl_since
    try:
        await asyncio.sleep(_RL_REPORT_SECONDS)
        if not _rl_count:
            return
        top = ", ".join(
            f"{cid}×{n}" for cid, n in sorted(_rl_channels.items(), key=lambda kv: -kv[1])[:5]
        )
        log.warning(
            "Rate limited: %d requête(s) en %.0f s · attente cumulée %.1f s (max %.1f s) · "
            "salons les plus touchés: %s%s",
            _rl_count, _RL_REPORT_SECONDS, _rl_total_wait, _rl_max_wait, top or "—",
            f" · dont {_rl_global} limite(s) globale(s)" if _rl_global else "",
        )
    finally:
        _rl_count = 0
        _rl_channels = {}
        _rl_total_wait = 0.0
        _rl_max_wait = 0.0
        _rl_global = 0
        _rl_since = 0.0


def rate_limit_snapshot() -> dict:
    """État courant (utilisé par /logstats et les diagnostics)."""
    return {
        "count": _rl_count,
        "channels": dict(_rl_channels),
        "wait_total": round(_rl_total_wait, 2),
        "wait_max": round(_rl_max_wait, 2),
        "global": _rl_global,
        "channels_tracked": len(_CHANNEL_LIMITERS),
    }


# ── Background queue worker (fire-and-forget) ────────────────────────────────
_send_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


def start_queue_worker() -> None:
    """Launch the background sender worker. Called once at startup."""
    global _send_queue, _worker_task
    if _worker_task is not None:
        return
    _send_queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _worker_task = asyncio.get_event_loop().create_task(_queue_worker())
    log.info("API queue worker started.")


async def stop_queue_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None


# File d'attente bornée : sous un très gros flood, mieux vaut perdre les
# entrées les plus anciennes (déjà quasi obsolètes) que saturer la mémoire —
# et on le dit, au lieu de faire disparaître des logs en silence.
_QUEUE_MAX = 3000
_queue_dropped = 0
_queue_workers = 4          # envois concurrents (le régulateur par salon pace derrière)
_queue_inflight = 0         # messages sortis de la file mais pas encore envoyés
_last_drop_report = 0.0


async def _queue_worker() -> None:
    """Consomme la file : un envoi concurrent par « slot », le reste patiente."""
    global _queue_inflight
    sem = asyncio.Semaphore(_queue_workers)
    tasks: set[asyncio.Task] = set()

    async def _send_one(item) -> None:
        global _queue_inflight
        channel_id, payload, allowed_mentions = item
        try:
            await api_send(channel_id, payload, allowed_mentions=allowed_mentions)
        except Exception as e:
            log.error("queue worker: %s", e)
        finally:
            _queue_inflight = max(0, _queue_inflight - 1)
            sem.release()
            _send_queue.task_done()

    while True:
        await sem.acquire()
        try:
            item = _send_queue.get_nowait()
        except asyncio.QueueEmpty:
            sem.release()
            if tasks:
                await asyncio.sleep(0.2)
                continue
            item = await _send_queue.get()
        _queue_inflight += 1
        task = asyncio.get_running_loop().create_task(_send_one(item))
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def queue_depth() -> int:
    """Messages ni envoyés ni perdus : en file **+** en cours d'envoi."""
    if _send_queue is None:
        return 0
    return _send_queue.qsize() + _queue_inflight


def _report_dropped() -> None:
    global _queue_dropped, _last_drop_report
    if not _queue_dropped:
        return
    now = time.monotonic()
    if now - _last_drop_report < 30.0:
        return
    _last_drop_report = now
    log.warning("File d'envoi saturée : %d message(s) abandonné(s).", _queue_dropped)
    _queue_dropped = 0


def api_send_queued(channel_id: int, payload: dict, allowed_mentions: dict | None = None) -> None:
    """Enqueue a message for background delivery (used for log spam)."""
    global _queue_dropped
    if _send_queue is None:
        # Worker not started yet — send directly as fallback.
        asyncio.get_event_loop().create_task(
            api_send(channel_id, payload, allowed_mentions=allowed_mentions)
        )
        return
    if _send_queue.full():
        try:
            _send_queue.get_nowait()   # on sacrifie l'entrée la plus ancienne
            _send_queue.task_done()
            _queue_dropped += 1
        except asyncio.QueueEmpty:
            pass
        _report_dropped()
    _send_queue.put_nowait((channel_id, payload, allowed_mentions))


# ── Media gallery helper ─────────────────────────────────────────────────────

def media_gallery(items: list[str] | list[tuple[str, str | None]]) -> dict:
    """Build a media-gallery component (type 12) — displays images inline."""
    out = []
    for it in items:
        url, desc = it if isinstance(it, tuple) else (it, None)
        entry: dict = {"media": {"url": url}}
        if desc:
            entry["description"] = desc
        out.append(entry)
    return {"type": 12, "items": out}


# ── Session ──────────────────────────────────────────────────────────────────

def get_session() -> aiohttp.ClientSession:
    if _session is None or _session.closed:
        raise RuntimeError("HTTP session not initialized.")
    return _session


async def init_session(token: str) -> None:
    global _session
    # NOTE: no global Content-Type header — aiohttp sets it per-request
    # (application/json for `json=`, multipart/form-data for FormData uploads).
    _session = aiohttp.ClientSession(headers={"Authorization": f"Bot {token}"})
    log.info("aiohttp session initialized.")


async def close_session() -> None:
    if _session and not _session.closed:
        await _session.close()
        log.info("aiohttp session closed.")


# ── Core send (with exponential backoff) ─────────────────────────────────────

async def _request_with_backoff(method: str, url: str, **kwargs) -> tuple[int, dict]:
    session = get_session()
    channel_id = _channel_id_from_url(url)
    retries = 0
    max_retries = 5
    while True:
        await _throttle(channel_id)
        async with session.request(method, url, **kwargs) as r:
            try:
                data = await r.json()
            except Exception:
                data = {}
            if r.status == 429:
                # Discord renvoie retry_after (secondes, déjà en float en v10).
                retry_after = float(data.get("retry_after", 1.0))
                is_global = bool(data.get("global")) or r.headers.get("X-RateLimit-Scope") == "global"
                backoff = retry_after + 0.15
                # On « punit » le bucket du salon : sinon les envois suivants
                # repartaient aussitôt et re-déclenchaient un 429 en cascade.
                if channel_id:
                    _channel_limiter(channel_id).penalize(backoff)
                if is_global:
                    # Limite globale Discord (toutes routes) : on bloque le bucket
                    # global, que TOUTES les requêtes traversent → tout le bot
                    # patiente au lieu de continuer à se faire refuser.
                    _GLOBAL_BUCKET.penalize(backoff)
                _rl_note(channel_id, backoff, is_global=is_global)
                retries += 1
                if retries > max_retries:
                    return 429, data
                await asyncio.sleep(backoff)
                continue
            if r.status >= 500 and retries < max_retries:
                backoff = 2 ** retries
                await asyncio.sleep(backoff)
                retries += 1
                continue
            if r.status not in (200, 201, 204):
                log.warning("%s %s → %s %s", method, url, r.status, data)
            return r.status, data


async def api_send(
    channel_id: int,
    payload: dict,
    *,
    retries: int = 3,
    allowed_mentions: dict | None = None,
) -> tuple[int, dict]:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload["allowed_mentions"] = allowed_mentions if allowed_mentions is not None else NO_MENTIONS
    return await _request_with_backoff("POST", url, json=payload)


async def api_edit(
    channel_id: int,
    message_id: int,
    payload: dict,
    *,
    retries: int = 3,
    allowed_mentions: dict | None = None,
) -> tuple[int, dict]:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    payload["allowed_mentions"] = allowed_mentions if allowed_mentions is not None else NO_MENTIONS
    return await _request_with_backoff("PATCH", url, json=payload)


async def api_send_file(
    channel_id: int,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    content: str | None = None,
    allowed_mentions: dict | None = None,
) -> tuple[int, dict]:
    """Upload a file (e.g. a generated rank card) to a channel.

    Uses the same throttle/backoff path as ``api_send`` so a 429 or 5xx never
    silently drops the upload.
    """
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload_json = {
        "allowed_mentions": allowed_mentions if allowed_mentions is not None else NO_MENTIONS,
    }
    if content:
        payload_json["content"] = content

    form = aiohttp.FormData()
    form.add_field("payload_json", _json_dumps(payload_json), content_type="application/json")
    form.add_field("files[0]", data, filename=filename, content_type=content_type)
    return await _request_with_backoff("POST", url, data=form)
