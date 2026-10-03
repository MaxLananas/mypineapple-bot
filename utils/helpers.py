from __future__ import annotations
import logging
from datetime import datetime, timezone
import discord

log = logging.getLogger(__name__)


MAX_LEVEL = 100


def xp_for_level(level: int) -> int:
    """XP required to advance *from* `level` to `level + 1`."""
    return 5 * (level ** 2) + 50 * level + 100


def xp_needed(level: int, max_level: int = MAX_LEVEL) -> int:
    """XP required to reach the next level, or 0 once at max level.

    Fixes the level-100 off-by-one: ``xp_for_level(100)`` targets a nonexistent
    level 101, so displays must treat max level as "fully progressed".
    """
    return 0 if level >= max_level else xp_for_level(level)


def progress_bar(current: int, needed: int, length: int = 12) -> str:
    pct = min(current / needed, 1.0) if needed else 0
    full = int(pct * length)
    return "▰" * full + "▱" * (length - full)


def ts_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


async def safe_add_role(member: discord.Member, role: discord.Role, reason: str = "") -> None:
    try:
        await member.add_roles(role, reason=reason)
    except discord.Forbidden:
        log.warning("Cannot add role %s to %s", role.name, member)
    except Exception as e:
        log.error("safe_add_role: %s", e)


async def safe_remove_role(member: discord.Member, role: discord.Role, reason: str = "") -> None:
    try:
        await member.remove_roles(role, reason=reason)
    except Exception as e:
        log.error("safe_remove_role: %s", e)


async def ack(interaction: discord.Interaction) -> None:
    """Silently acknowledge an interaction without sending a visible message."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
    except Exception:
        pass