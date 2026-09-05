#!/usr/bin/env python3
"""Migration SQLite <-> PostgreSQL pour MyPineapple Bot.

Utilisation :
    # 1) Exporter la DB SQLite locale vers un fichier JSON (sauvegarde)
    python scripts/migrate_db.py export --source data/bot.db --out migration_export.json

    # 2) Importer le JSON vers PostgreSQL (Neon) — lit DATABASE_URL
    python scripts/migrate_db.py import --in migration_export.json

    # 3) Ou transfert direct SQLite -> PostgreSQL (sans fichier intermédiaire)
    python scripts/migrate_db.py direct --source data/bot.db

Le schéma est identique des deux côtés : table `kv_store (store, key, value)`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import aiosqlite

TABLE = "kv_store"
STORES = ["levels", "tickets", "config", "daily", "warns", "ticketlogs"]


async def _read_sqlite(path: str) -> list[tuple[str, str, str]]:
    con = await aiosqlite.connect(path)
    con.row_factory = aiosqlite.Row
    try:
        async with con.execute(
            f"SELECT store, key, value FROM {TABLE} ORDER BY store, key"
        ) as cur:
            rows = [tuple(r) async for r in cur]
    finally:
        await con.close()
    return rows


async def _write_postgres(dsn: str, rows: list[tuple[str, str, str]]) -> int:
    import asyncpg
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as con:
            await con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    store TEXT NOT NULL,
                    key   TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (store, key)
                )
                """
            )
            async with con.transaction():
                await con.execute(f"DELETE FROM {TABLE}")
                if rows:
                    await con.executemany(
                        f"INSERT INTO {TABLE} (store, key, value) VALUES ($1, $2, $3)",
                        rows,
                    )
    finally:
        await pool.close()
    return len(rows)


async def _write_sqlite(path: str, rows: list[tuple[str, str, str]]) -> int:
    con = await aiosqlite.connect(path)
    try:
        await con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                store TEXT NOT NULL,
                key   TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (store, key)
            )
            """
        )
        await con.execute(f"DELETE FROM {TABLE}")
        if rows:
            await con.executemany(
                f"INSERT INTO {TABLE} (store, key, value) VALUES (?, ?, ?)", rows
            )
        await con.commit()
    finally:
        await con.close()
    return len(rows)


def _summary(rows: list[tuple[str, str, str]]) -> str:
    from collections import Counter
    c = Counter(r[0] for r in rows)
    return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "(vide)"


async def cmd_export(source: str, out: str) -> None:
    rows = await _read_sqlite(source)
    payload = {"schema": TABLE, "rows": [list(r) for r in rows]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✓ Exporté {len(rows)} lignes vers {out}  [{_summary(rows)}]")


async def cmd_import(inp: str, dsn: str, target_sqlite: str | None) -> None:
    with open(inp, encoding="utf-8") as f:
        payload = json.load(f)
    rows = [tuple(r) for r in payload["rows"]]
    if target_sqlite:
        n = await _write_sqlite(target_sqlite, rows)
        print(f"✓ Importé {n} lignes vers SQLite {target_sqlite}")
    else:
        n = await _write_postgres(dsn, rows)
        print(f"✓ Importé {n} lignes vers PostgreSQL  [{_summary(rows)}]")


async def cmd_direct(source: str, dsn: str) -> None:
    rows = await _read_sqlite(source)
    n = await _write_postgres(dsn, rows)
    print(f"✓ Transféré {n} lignes de {source} vers PostgreSQL  [{_summary(rows)}]")


def main() -> None:
    p = argparse.ArgumentParser(description="Migration DB MyPineapple")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("--source", default="data/bot.db")
    e.add_argument("--out", default="migration_export.json")

    i = sub.add_parser("import")
    i.add_argument("--in", dest="inp", default="migration_export.json")
    i.add_argument("--sqlite", default=None, help="Cible SQLite alternative au lieu de Postgres")

    d = sub.add_parser("direct")
    d.add_argument("--source", default="data/bot.db")

    args = p.parse_args()

    if args.cmd == "export":
        asyncio.run(cmd_export(args.source, args.out))
        return

    if args.cmd == "import":
        if args.sqlite:
            asyncio.run(cmd_import(args.inp, "", args.sqlite))
            return
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            sys.exit("❌ DATABASE_URL non défini. Exemple :\n"
                     "   export DATABASE_URL='postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require'")
        asyncio.run(cmd_import(args.inp, dsn, None))
        return

    if args.cmd == "direct":
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            sys.exit("❌ DATABASE_URL non défini.")
        asyncio.run(cmd_direct(args.source, dsn))
        return


if __name__ == "__main__":
    main()
