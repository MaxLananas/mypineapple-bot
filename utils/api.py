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

# ── Global rate limiter ──────────────────────────────────────────────────────
# Simple token-ish limiter: keeps a short history of send timestamps and sleeps
# when we approach Discord's per-route budget. Not a hard queue, but enough to
# smooth out bursts (e.g. a flood of log events).
_send_times: list[float] = []
_limiter_lock = asyncio.Lock()
_MAX_SENDS_PER_WINDOW = 45   # conservative
_WINDOW_SECONDS = 10.0


async def _throttle() -> None:
    global _send_times
    async with _limiter_lock:
        now = time.monotonic()
        _send_times = [t for t in _send_times if now - t < _WINDOW_SECONDS]
        if len(_send_times) >= _MAX_SENDS_PER_WINDOW:
            oldest = _send_times[0]
            wait = _WINDOW_SECONDS - (now - oldest) + 0.05
            await asyncio.sleep(wait)
            now = time.monotonic()
            _send_times = [t for t in _send_times if now - t < _WINDOW_SECONDS]
        _send_times.append(now)


# ── Background queue worker (fire-and-forget) ────────────────────────────────
_send_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


def start_queue_worker() -> None:
    """Launch the background sender worker. Called once at startup."""
    global _send_queue, _worker_task
    if _worker_task is not None:
        return
    _send_queue = asyncio.Queue()
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


async def _queue_worker() -> None:
    while True:
        channel_id, payload, allowed_mentions = await _send_queue.get()
        try:
            await api_send(channel_id, payload, allowed_mentions=allowed_mentions)
        except Exception as e:
            log.error("queue worker: %s", e)
        finally:
            _send_queue.task_done()
        await asyncio.sleep(0.05)  # slight pacing between queued sends


def api_send_queued(channel_id: int, payload: dict, allowed_mentions: dict | None = None) -> None:
    """Enqueue a message for background delivery (used for log spam)."""
    if _send_queue is None:
        # Worker not started yet — send directly as fallback.
        asyncio.get_event_loop().create_task(
            api_send(channel_id, payload, allowed_mentions=allowed_mentions)
        )
        return
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
    global _session
    if _session and not _session.closed:
        await _session.close()
        log.info("aiohttp session closed.")


# ── Core send (with exponential backoff) ─────────────────────────────────────

async def _request_with_backoff(method: str, url: str, **kwargs) -> tuple[int, dict]:
    session = get_session()
    retries = 0
    max_retries = 5
    while True:
        await _throttle()
        async with session.request(method, url, **kwargs) as r:
            try:
                data = await r.json()
            except Exception:
                data = {}
            if r.status == 429:
                retry_after = float(data.get("retry_after", 1.0))
                backoff = retry_after + 0.1 + (retries * 0.5)
                log.warning("Rate limited (%s), retrying in %.2fs", url, backoff)
                await asyncio.sleep(backoff)
                retries += 1
                if retries > max_retries:
                    return 429, data
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
