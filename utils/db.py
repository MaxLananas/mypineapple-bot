from __future__ import annotations
import asyncio
import json
import logging
import os
import time
import aiosqlite

log = logging.getLogger(__name__)

# ── Backend selection ────────────────────────────────────────────────────────
# 3 backends possibles, priorité :
#   1. PostgreSQL (DATABASE_URL)   → base hébergée, survit à tout.
#   2. Discord     (DB_CHANNEL_ID) → snapshot JSON uploadé dans un salon Discord.
#                                    Survit aux restarts, AUCUN serveur requis.
#   3. SQLite local (défaut)       → data/bot.db (perdu sur hébergeur qui reclone).
#
# L'idée « DB dans un salon Discord » : à chaque flush, le bot envoie un fichier
# `db_snapshot.json` (pièce jointe) dans le salon. Au démarrage, il télécharge la
# dernière snapshot pour restaurer l'état. Discord = stockage persistant gratuit.
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
try:
    from config import DB_CHANNEL_ID  # salon de sauvegarde
except Exception:
    DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID", "")

SNAPSHOT_FILENAME = "db_snapshot.json"
MIN_SNAPSHOT_INTERVAL = 30.0  # secondes min entre 2 snapshots Discord

if DATABASE_URL:
    _backend = "postgres"
elif DB_CHANNEL_ID:
    _backend = "discord"
else:
    _backend = "sqlite"

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

_db = None
_http = None  # session aiohttp dédiée au backend Discord

_cache: dict[str, dict] = {}
_dirty: set[str] = set()
_lock: asyncio.Lock = asyncio.Lock()
_checkpoint_counter = 0

# Backend Discord : message snapshot courant + horodatage du dernier envoi.
_discord_last_msg_id: str | None = None
_discord_last_send = 0.0

STORES = ["levels", "tickets", "config", "daily", "warns", "ticketlogs", "stats", "closedtickets"]


def _json_dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)


# ── Init ─────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    global _db, _http
    if _backend == "postgres":
        _db = await _init_postgres()
    elif _backend == "discord":
        _http = await _init_discord()
        found = await _load_from_discord()
        if not found:
            # Aucun snapshot dans le salon : on tente une migration depuis le
            # SQLite local (si un data/bot.db traîne encore sur cet hôte).
            migrated = await _migrate_from_local_sqlite()
            if migrated:
                log.info("Migrated local SQLite data → Discord snapshot.")
                await _flush_all()
            else:
                log.info("No existing data found — starting fresh (discord backend).")
        log.info("DB initialized (discord channel %s).", DB_CHANNEL_ID)
        return
    else:
        _db = await _init_sqlite()
    await _load_all()
    log.info("DB initialized (%s).", _backend)


async def _init_sqlite():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=10000")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv_store (
            store TEXT NOT NULL,
            key   TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (store, key)
        )
        """
    )
    await conn.commit()
    return conn


async def _init_postgres():
    import asyncpg

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                store TEXT NOT NULL,
                key   TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (store, key)
            )
            """
        )
    return pool


async def _init_discord():
    import aiohttp
    from config import TOKEN

    return aiohttp.ClientSession(headers={"Authorization": f"Bot {TOKEN}"})


async def close_db() -> None:
    try:
        await _flush_all()
    except Exception as e:
        log.error("close_db flush: %s", e)
    if _backend == "postgres":
        await _db.close()
    elif _backend == "sqlite":
        await _db.close()
    elif _backend == "discord" and _http:
        await _http.close()
    log.info("DB closed.")


# ── Load ─────────────────────────────────────────────────────────────────────

async def _load_all() -> None:
    for store in STORES:
        _cache[store] = {}

    if _backend == "postgres":
        async with _db.acquire() as conn:
            rows = await conn.fetch("SELECT store, key, value FROM kv_store")
        for row in rows:
            _ingest(row["store"], row["key"], row["value"])
    else:
        async with _db.execute("SELECT store, key, value FROM kv_store") as cur:
            async for row in cur:
                _ingest(row["store"], row["key"], row["value"])
    log.info("DB loaded into memory: %d stores.", len(STORES))


def _ingest(store: str, key: str, value: str) -> None:
    if store not in _cache:
        return
    try:
        _cache[store][key] = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        pass


async def _load_from_discord() -> bool:
    for store in STORES:
        _cache[store] = {}

    url = f"https://discord.com/api/v10/channels/{DB_CHANNEL_ID}/messages?limit=100"
    try:
        async with _http.get(url) as r:
            if r.status != 200:
                log.warning("Discord DB fetch → %s", r.status)
                return False
            messages = await r.json()
    except Exception as e:
        log.error("Discord DB fetch: %s", e)
        return False

    for msg in messages:
        for att in msg.get("attachments", []):
            if att.get("filename") == SNAPSHOT_FILENAME:
                try:
                    async with _http.get(att["url"]) as fr:
                        data = json.loads(await fr.read())
                    for store, items in data.items():
                        if store in _cache and isinstance(items, dict):
                            _cache[store].update(items)
                    global _discord_last_msg_id
                    _discord_last_msg_id = msg["id"]
                    log.info("Discord DB snapshot restored (%s).", msg["id"])
                    return True
                except Exception as e:
                    log.error("Discord DB snapshot parse: %s", e)
                    return False
    return False


async def _migrate_from_local_sqlite() -> bool:
    """Importe un data/bot.db local (si présent) dans le cache mémoire,
    puis marque tout comme "dirty" pour l'upload vers Discord."""
    if not os.path.exists(DB_PATH):
        return False
    try:
        con = await aiosqlite.connect(DB_PATH)
        con.row_factory = aiosqlite.Row
        async with con.execute("SELECT store, key, value FROM kv_store") as cur:
            rows = [tuple(r) async for r in cur]
        await con.close()
    except Exception as e:
        log.warning("Local SQLite migration skipped: %s", e)
        return False

    if not rows:
        return False
    for store, key, value in rows:
        _ingest(store, key, value)
    async with _lock:
        _dirty.update(STORES)
    log.info("Imported %d rows from local SQLite.", len(rows))
    return True


# ── Flush ────────────────────────────────────────────────────────────────────

async def _flush_all() -> None:
    async with _lock:
        dirty = list(_dirty)
        _dirty.clear()

    if not dirty:
        return

    if _backend == "postgres":
        for store in dirty:
            data = _cache.get(store, {})
            async with _db.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM kv_store WHERE store = $1", store)
                    if data:
                        await conn.executemany(
                            "INSERT INTO kv_store (store, key, value) VALUES ($1, $2, $3)",
                            [(store, k, _json_dumps(v)) for k, v in data.items()],
                        )
    elif _backend == "discord":
        await _flush_discord(dirty)
    else:
        for store in dirty:
            await _flush_store_sqlite(store, _cache.get(store, {}))
        await _checkpoint_wal()


async def _flush_discord(dirty: list[str]) -> None:
    global _discord_last_msg_id, _discord_last_send

    now = time.time()
    if now - _discord_last_send < MIN_SNAPSHOT_INTERVAL:
        # Remet les stores en "dirty" pour ne pas perdre les changements.
        async with _lock:
            _dirty.update(dirty)
        return

    # Snapshot complet de tous les stores non vides.
    snapshot = {s: _cache.get(s, {}) for s in STORES if _cache.get(s)}
    blob = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    summary = ", ".join(f"{s}:{len(_cache.get(s, {}))}" for s in sorted(snapshot))

    import aiohttp

    form = aiohttp.FormData()
    form.add_field(
        "payload_json",
        json.dumps({"content": f"🍍 **DB snapshot** — {summary}"}),
        content_type="application/json",
    )
    form.add_field(
        "files[0]",
        blob,
        filename=SNAPSHOT_FILENAME,
        content_type="application/json",
    )

    url = f"https://discord.com/api/v10/channels/{DB_CHANNEL_ID}/messages"
    try:
        async with _http.post(url, data=form) as r:
            if r.status in (200, 201):
                data = await r.json()
                new_id = data.get("id")
                _discord_last_send = now
                if _discord_last_msg_id:
                    # Nettoie l'ancien snapshot (garde le salon propre).
                    try:
                        async with _http.delete(
                            f"{url}/{_discord_last_msg_id}"
                        ) as dr:
                            pass
                    except Exception:
                        pass
                _discord_last_msg_id = new_id
            elif r.status == 429:
                async with _lock:
                    _dirty.update(dirty)
                log.warning("Discord DB snapshot rate-limited.")
            else:
                async with _lock:
                    _dirty.update(dirty)
                log.warning("Discord DB snapshot → %s", r.status)
    except Exception as e:
        async with _lock:
            _dirty.update(dirty)
        log.error("Discord DB snapshot: %s", e)


async def _flush_store_sqlite(store: str, data: dict) -> None:
    async with _db.executemany(
        "INSERT OR REPLACE INTO kv_store (store, key, value) VALUES (?, ?, ?)",
        [(store, k, _json_dumps(v)) for k, v in data.items()],
    ):
        pass

    keys = set(data.keys())
    async with _db.execute(
        "SELECT key FROM kv_store WHERE store = ?", (store,)
    ) as cur:
        db_keys = {row["key"] async for row in cur}
    orphans = db_keys - keys
    if orphans:
        await _db.executemany(
            "DELETE FROM kv_store WHERE store = ? AND key = ?",
            [(store, k) for k in orphans],
        )
    await _db.commit()


async def _checkpoint_wal() -> None:
    global _checkpoint_counter
    _checkpoint_counter += 1
    if _checkpoint_counter % 20 == 0:
        try:
            await _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await _db.commit()
        except Exception as e:
            log.warning("wal_checkpoint: %s", e)


async def flush() -> None:
    """Flush all pending changes immediately (used on graceful shutdown)."""
    await _flush_all()


async def flush_loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await _flush_all()
        except Exception as e:
            log.error("flush_loop: %s", e)
        await asyncio.sleep(15)


# ── Accesseurs ───────────────────────────────────────────────────────────────

def _get(store: str) -> dict:
    return _cache.get(store, {})


def _set(store: str, data: dict) -> None:
    _cache[store] = data
    _dirty.add(store)


def levels()     -> dict: return _get("levels")
def tickets()    -> dict: return _get("tickets")
def config()     -> dict: return _get("config")
def daily()      -> dict: return _get("daily")
def warns()      -> dict: return _get("warns")
def ticketlogs()     -> dict: return _get("ticketlogs")
def stats()          -> dict: return _get("stats")
def closedtickets()  -> dict: return _get("closedtickets")

def save_levels(d: dict)     -> None: _set("levels", d)
def save_tickets(d: dict)    -> None: _set("tickets", d)
def save_config(d: dict)     -> None: _set("config", d)
def save_daily(d: dict)      -> None: _set("daily", d)
def save_warns(d: dict)      -> None: _set("warns", d)
def save_ticketlogs(d: dict)     -> None: _set("ticketlogs", d)
def save_stats(d: dict)          -> None: _set("stats", d)
def save_closedtickets(d: dict)  -> None: _set("closedtickets", d)


def setup() -> None:
    global _lock
    _lock = asyncio.Lock()


async def ping() -> float:
    """Healthcheck: measure DB round-trip latency in milliseconds.

    Returns -1.0 if the DB is unreachable (detects a dead backend).
    """
    import time
    start = time.perf_counter()
    try:
        if _backend == "postgres":
            async with _db.acquire() as conn:
                await conn.fetchval("SELECT 1")
        elif _backend == "discord":
            # No synchronous query; the in-memory cache is always "up".
            pass
        else:
            async with _db.execute("SELECT 1"):
                pass
    except Exception as e:
        log.error("db.ping: %s", e)
        return -1.0
    return (time.perf_counter() - start) * 1000.0
