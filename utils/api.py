from __future__ import annotations
import asyncio
import aiohttp
import logging

log = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None

NO_MENTIONS = {
    "parse":        [],
    "roles":        [],
    "users":        [],
    "replied_user": False,
}

# Pour les messages qui DOIVENT ping (annonces…).
MENTIONS_ALL = {
    "parse":        ["users", "roles", "everyone"],
    "replied_user": True,
}


def media_gallery(items: list[str] | list[tuple[str, str | None]]) -> dict:
    """Construit un composant galerie média (type 12) — affiche les images/vidéos
    en ligne plutôt qu'un lien texte."""
    out = []
    for it in items:
        url, desc = it if isinstance(it, tuple) else (it, None)
        entry: dict = {"media": {"url": url}}
        if desc:
            entry["description"] = desc
        out.append(entry)
    return {"type": 12, "items": out}


def get_session() -> aiohttp.ClientSession:
    if _session is None or _session.closed:
        raise RuntimeError("HTTP session not initialized.")
    return _session


async def init_session(token: str) -> None:
    global _session
    _session = aiohttp.ClientSession(
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type":  "application/json",
        }
    )
    log.info("aiohttp session initialized.")


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        log.info("aiohttp session closed.")


async def api_send(
    channel_id: int,
    payload: dict,
    *,
    retries: int = 3,
    allowed_mentions: dict | None = None,
) -> tuple[int, dict]:
    session = get_session()
    url     = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload["allowed_mentions"] = allowed_mentions if allowed_mentions is not None else NO_MENTIONS
    for _ in range(retries):
        async with session.post(url, json=payload) as r:
            try:
                data = await r.json()
            except Exception:
                data = {}
            if r.status == 429:
                retry_after = data.get("retry_after", 1.0)
                log.warning("Rate limited api_send, retrying in %.2fs", retry_after)
                await asyncio.sleep(float(retry_after) + 0.1)
                continue
            if r.status not in (200, 201):
                log.warning("api_send → %s %s", r.status, data)
            return r.status, data
    return 429, {}


async def api_edit(
    channel_id: int,
    message_id: int,
    payload: dict,
    *,
    retries: int = 3,
    allowed_mentions: dict | None = None,
) -> tuple[int, dict]:
    session = get_session()
    url     = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    payload["allowed_mentions"] = allowed_mentions if allowed_mentions is not None else NO_MENTIONS
    for _ in range(retries):
        async with session.patch(url, json=payload) as r:
            try:
                data = await r.json()
            except Exception:
                data = {}
            if r.status == 429:
                retry_after = data.get("retry_after", 1.0)
                log.warning("Rate limited api_edit, retrying in %.2fs", retry_after)
                await asyncio.sleep(float(retry_after) + 0.1)
                continue
            return r.status, data
    return 429, {}