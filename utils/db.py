from __future__ import annotations
import asyncio
import json
import logging
import os
import aiosqlite

log = logging.getLogger(__name__)

# ── Backend selection ────────────────────────────────────────────────────────
# Par défaut : SQLite local (fichier data/bot.db). Rapide, zéro config.
# Pour un hébergeur qui "re-clone" le repo à chaque restart (bot-hosting.net,
# Replit, etc.), le système de fichiers est éphémère : tout ce qui n'est pas
# dans git est perdu. La solution robuste est une base hébergée :
#   DATABASE_URL=postgres://user:pass@host:5432/dbname
# (Neon / Supabase / Railway proposent un palier gratuit). Quand DATABASE_URL
# est défini, le bot utilise PostgreSQL et la progression survit à tout restart.
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

_db = None
_backend = "postgres" if DATABASE_URL else "sqlite"

_cache: dict[str, dict] = {}
_dirty: set[str] = set()
_lock: asyncio.Lock = asyncio.Lock()
_checkpoint_counter = 0

STORES = ["levels", "tickets", "config", "daily", "warns", "ticketlogs"]


def _json_dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)


async def init_db() -> None:
    global _db
    if _backend == "postgres":
        _db = await _init_postgres()
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


async def close_db() -> None:
    if _db is None:
        return
    try:
        await _flush_all()
    except Exception as e:
        log.error("close_db flush: %s", e)
    if _backend == "postgres":
        await _db.close()
    else:
        await _db.close()
    log.info("DB closed.")


async def _load_all() -> None:
    for store in STORES:
        _cache[store] = {}

    if _backend == "postgres":
        async with _db.acquire() as conn:
            rows = await conn.fetch("SELECT store, key, value FROM kv_store")
        for row in rows:
            store = row["store"]
            if store in _cache:
                try:
                    _cache[store][row["key"]] = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
    else:
        async with _db.execute("SELECT store, key, value FROM kv_store") as cur:
            async for row in cur:
                store = row["store"]
                if store in _cache:
                    try:
                        _cache[store][row["key"]] = json.loads(row["value"])
                    except (json.JSONDecodeError, TypeError):
                        pass
    log.info("DB loaded into memory: %d stores.", len(STORES))


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
    else:
        for store in dirty:
            data = _cache.get(store, {})
            await _flush_store_sqlite(store, data)
        await _checkpoint_wal()


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
    """Plie le WAL dans le fichier principal pour que data/bot.db soit complet
    (utile si on continue de versionner le fichier dans git)."""
    global _checkpoint_counter
    _checkpoint_counter += 1
    if _checkpoint_counter % 20 == 0:  # ~ toutes les 5 minutes
        try:
            await _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await _db.commit()
        except Exception as e:
            log.warning("wal_checkpoint: %s", e)


async def flush_loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await _flush_all()
        except Exception as e:
            log.error("flush_loop: %s", e)
        await asyncio.sleep(15)


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
def ticketlogs() -> dict: return _get("ticketlogs")

def save_levels(d: dict)     -> None: _set("levels", d)
def save_tickets(d: dict)    -> None: _set("tickets", d)
def save_config(d: dict)     -> None: _set("config", d)
def save_daily(d: dict)      -> None: _set("daily", d)
def save_warns(d: dict)      -> None: _set("warns", d)
def save_ticketlogs(d: dict) -> None: _set("ticketlogs", d)


def setup() -> None:
    global _lock
    _lock = asyncio.Lock()
