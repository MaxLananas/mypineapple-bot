"""Intelligent anti-spam with escalating, self-removing mutes.

Detects *repetitive* spam (same normalized message repeated) and rapid-fire,
then mutes the offender with increasing severity:

    offense 1 → 10 minutes
    offense 2 → 1 hour
    offense 3 → 10 hours (and every subsequent offense)

Each escalation also applies a "warn" role so admins can see repeat offenders.
The mute role is automatically removed when the timeout expires.
"""
from __future__ import annotations
import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord

import utils.db as db
from utils.helpers import safe_add_role, safe_remove_role
from config import (
    ANTISPAM_MUTED_ROLE_ID,
    ANTISPAM_WARN_ROLES,
    ANTISPAM_DURATIONS,
)

log = logging.getLogger(__name__)

_IDENTICAL_THRESHOLD = 4
_IDENTICAL_WINDOW    = 6.0
_RAPID_THRESHOLD     = 6
_RAPID_WINDOW        = 3.0

_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=12))

_NORMALIZE_RE = re.compile(r"\s+")
_MAX_TRACKED_USERS = 2000  # bound memory: drop the oldest idle users past this


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", text.strip().lower())


async def process_message(message: discord.Message) -> bool:
    """Inspect a message for spam. Returns True if the author was muted."""
    if message.author.bot or not message.guild:
        return False

    uid = message.author.id
    now = time.time()
    content = _normalize(message.content) if message.content else None

    hist = _history[uid]
    hist.append((now, content))

    # Bound the per-user history map (avoids unbounded growth on big servers).
    if len(_history) > _MAX_TRACKED_USERS:
        for key in list(_history)[:_MAX_TRACKED_USERS // 2]:
            if key != uid:
                _history.pop(key, None)

    recent = [(t, c) for t, c in hist if now - t <= max(_IDENTICAL_WINDOW, _RAPID_WINDOW)]

    # 1) Repetitive: same normalized message repeated.
    if content:
        identical = [1 for t, c in recent if c == content]
        if len(identical) >= _IDENTICAL_THRESHOLD:
            await _escalate(message.author)
            _history[uid].clear()
            return True

    # 2) Rapid-fire: too many messages in a short burst.
    if len(recent) >= _RAPID_THRESHOLD:
        await _escalate(message.author)
        _history[uid].clear()
        return True

    return False


_OFFENSE_DECAY = 24 * 3600  # reset the counter after 24h of good behaviour


def _offense_of(uid: int) -> int:
    # Persist offense counts so they survive restarts.
    data = db.config()
    counts = data.setdefault("antispam_offenses", {})
    rec = counts.get(str(uid), 0)
    # Legacy schema: plain int (no timestamp).
    if isinstance(rec, int):
        return rec
    if isinstance(rec, dict):
        last = rec.get("at", 0)
        if time.time() - last > _OFFENSE_DECAY:
            return 0  # decayed
        return int(rec.get("count", 0))
    return 0


def _set_offense(uid: int, n: int) -> None:
    data = db.config()
    counts = data.setdefault("antispam_offenses", {})
    counts[str(uid)] = {"count": n, "at": time.time()}
    db.save_config(data)


async def _escalate(member: discord.Member) -> None:
    guild = member.guild
    offense = _offense_of(member.id) + 1
    _set_offense(member.id, offense)

    idx = min(offense - 1, len(ANTISPAM_DURATIONS) - 1)
    duration = ANTISPAM_DURATIONS[idx]

    muted_role = guild.get_role(ANTISPAM_MUTED_ROLE_ID)
    warn_role = None
    if idx < len(ANTISPAM_WARN_ROLES):
        warn_role = guild.get_role(ANTISPAM_WARN_ROLES[idx])

    try:
        await member.timeout(
            datetime.now(timezone.utc) + timedelta(seconds=duration),
            reason=f"Anti-spam (offense {offense})",
        )
    except discord.Forbidden:
        log.warning("Cannot timeout %s (missing permission)", member)
        return
    except Exception as e:
        log.error("timeout %s: %s", member, e)

    if muted_role:
        await safe_add_role(member, muted_role, reason=f"Anti-spam offense {offense}")
    if warn_role:
        await safe_add_role(member, warn_role, reason=f"Anti-spam warn level {idx + 1}")

    log.info("Anti-spam: muted %s for %ss (offense %d)", member, duration, offense)

    until = time.time() + duration
    # Persisté : si le bot redémarre, `restore_pending_releases()` reprogramme le
    # retrait des rôles (sinon le rôle "muted" restait appliqué indéfiniment).
    _remember_timeout(
        member.id, guild.id,
        muted_role.id if muted_role else None,
        warn_role.id if warn_role else None,
        until,
    )
    # Auto-remove the muted role when the timeout expires.
    asyncio.create_task(_release_roles_after(
        guild.id, member.id,
        muted_role.id if muted_role else None,
        warn_role.id if warn_role else None,
        duration,
    ))


# ── Persistance des mutes en cours ───────────────────────────────────────────
# Sans ça, un restart du bot perdait les tâches de retrait : le membre gardait
# le rôle "muted" à vie (le timeout Discord expirait, pas le rôle).
_TIMEOUTS_KEY = "antispam_timeouts"
_bot: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    global _bot
    _bot = bot


def _remember_timeout(uid: int, guild_id: int, muted_id: int | None,
                      warn_id: int | None, until: float) -> None:
    data = db.config()
    data.setdefault(_TIMEOUTS_KEY, {})[str(uid)] = {
        "guild_id": guild_id,
        "muted":    muted_id,
        "warn":     warn_id,
        "until":    until,
    }
    db.save_config(data)


def _forget_timeout(uid: int) -> None:
    data = db.config()
    pending = data.get(_TIMEOUTS_KEY)
    if isinstance(pending, dict) and pending.pop(str(uid), None) is not None:
        db.save_config(data)


async def _release_roles_after(guild_id: int, member_id: int,
                               muted_id: int | None, warn_id: int | None,
                               delay: float) -> None:
    """Retire les rôles anti-spam après ``delay`` secondes (version robuste au
    restart : tout est en base, pas en mémoire)."""
    try:
        if _bot is not None:
            await _bot.wait_until_ready()
        if delay > 0:
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass

    try:
        guild = _bot.get_guild(guild_id) if _bot else None
        member = guild.get_member(member_id) if guild else None
        if member is not None:
            for rid in (muted_id, warn_id):
                if not rid:
                    continue
                role = guild.get_role(rid)
                if role and role in member.roles:
                    await safe_remove_role(member, role, reason="Anti-spam punishment expired")
    except Exception as e:
        log.error("release roles %s: %s", member_id, e)
    finally:
        _forget_timeout(member_id)


async def restore_pending_releases() -> int:
    """Replanifie les retraits de rôles en attente au démarrage.

    Retourne le nombre de mutes restaurés.
    """
    pending = db.config().get(_TIMEOUTS_KEY, {})
    if not isinstance(pending, dict) or not pending:
        return 0
    now = time.time()
    restored = 0
    for uid_str, rec in list(pending.items()):
        if not isinstance(rec, dict):
            pending.pop(uid_str, None)
            continue
        try:
            member_id = int(uid_str)
            guild_id  = int(rec.get("guild_id", 0))
        except (TypeError, ValueError):
            pending.pop(uid_str, None)
            continue
        delay = max(0.0, float(rec.get("until", 0) or 0) - now)
        asyncio.create_task(_release_roles_after(
            guild_id, member_id, rec.get("muted"), rec.get("warn"), delay
        ))
        restored += 1
    db.save_config(db.config())
    if restored:
        log.info("Anti-spam: %d mute(s) restauré(s) après restart.", restored)
    return restored
