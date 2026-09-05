from __future__ import annotations
import asyncio
import json
import logging
import os
import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = "data/bot.db"
os.makedirs("data", exist_ok=True)

_db: aiosqlite.Connection | None = None
_cache: dict[str, dict] = {}
_dirty: set[str] = set()
_lock: asyncio.Lock = asyncio.Lock()

STORES = ["levels", "tickets", "config", "daily", "warns"]


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.execute("PRAGMA cache_size=10000")
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS kv_store (
            store TEXT NOT NULL,
            key   TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (store, key)
        )
    """)
    await _db.commit()
    await _load_all()
    log.info("SQLite DB initialized.")


async def close_db() -> None:
    if _db:
        await _flush_all()
        await _db.close()
        log.info("SQLite DB closed.")


async def _load_all() -> None:
    for store in STORES:
        _cache[store] = {}
    async with _db.execute("SELECT store, key, value FROM kv_store") as cur:
        async for row in cur:
            store = row["store"]
            if store in _cache:
                try:
                    _cache[store][row["key"]] = json.loads(row["value"])
                except json.JSONDecodeError:
                    pass
    log.info("DB loaded into memory: %d stores", len(STORES))


async def _flush_all() -> None:
    async with _lock:
        dirty = list(_dirty)
        _dirty.clear()
    for store in dirty:
        data = _cache.get(store, {})
        async with _db.executemany(
            "INSERT OR REPLACE INTO kv_store (store, key, value) VALUES (?, ?, ?)",
            [(store, k, json.dumps(v, ensure_ascii=False)) for k, v in data.items()],
        ):
            pass
        keys = set(data.keys())
        async with _db.execute(
            f"SELECT key FROM kv_store WHERE store = ?", (store,)
        ) as cur:
            db_keys = {row["key"] async for row in cur}
        orphans = db_keys - keys
        if orphans:
            await _db.executemany(
                "DELETE FROM kv_store WHERE store = ? AND key = ?",
                [(store, k) for k in orphans],
            )
        await _db.commit()


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


def levels()  -> dict: return _get("levels")
def tickets() -> dict: return _get("tickets")
def config()  -> dict: return _get("config")
def daily()   -> dict: return _get("daily")
def warns()   -> dict: return _get("warns")

def save_levels(d: dict)  -> None: _set("levels", d)
def save_tickets(d: dict) -> None: _set("tickets", d)
def save_config(d: dict)  -> None: _set("config", d)
def save_daily(d: dict)   -> None: _set("daily", d)
def save_warns(d: dict)   -> None: _set("warns", d)


def setup() -> None:
    global _lock
    _lock = asyncio.Lock()