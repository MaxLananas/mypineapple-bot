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

    # Auto-remove the muted role when the timeout expires.
    asyncio.create_task(_release_after(member, muted_role, warn_role, duration))


async def _release_after(member, muted_role, warn_role, duration):
    await asyncio.sleep(duration)
    try:
        # Refetch: roles may have changed.
        m = member.guild.get_member(member.id)
        if m is None:
            return
        if muted_role and muted_role in m.roles:
            await safe_remove_role(m, muted_role, reason="Anti-spam mute expired")
    except Exception as e:
        log.error("release mute %s: %s", member, e)
