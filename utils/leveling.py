from __future__ import annotations
import logging

import discord

import utils.db as db
from utils.api import api_send
from utils.helpers import (
    xp_for_level,
    progress_bar,
    safe_add_role,
    safe_remove_role,
)
from config import LEVEL_ROLES, LEVEL_ROLE_NAMES

log = logging.getLogger(__name__)

MAX_LEVEL = 100


def milestone_roles_crossed(old_level: int, new_level: int) -> list[int]:
    """Milestones franchis en passant de old_level à new_level (exclusif/ inclusif)."""
    return [l for l in sorted(LEVEL_ROLES) if old_level < l <= new_level]


async def sync_level_roles(
    guild: discord.Guild,
    member: discord.Member,
    level: int,
) -> None:
    """Aligne les rôles palier sur le niveau réel :
    ajoute les rôles ≤ level, retire ceux > level. Idempotent."""
    for milestone, role_id in LEVEL_ROLES.items():
        role = guild.get_role(role_id)
        if not role:
            continue
        if level >= milestone:
            await safe_add_role(member, role, reason=f"Level {milestone} milestone")
        else:
            await safe_remove_role(member, role, reason=f"Level below {milestone}")


async def add_xp(
    guild: discord.Guild,
    member: discord.Member,
    amount: int,
    channel: discord.TextChannel | None = None,
) -> tuple[int, int] | None:
    """Ajoute de l'XP, gère les montées de niveau multiples, synchronise les
    rôles et envoie le message de level-up. Retourne (old, new) si montée."""
    data = db.levels()
    guild_id = str(guild.id)
    user_id = str(member.id)

    ud = data.setdefault(guild_id, {}).setdefault(user_id, {"xp": 0, "level": 0})
    old_level = ud["level"]
    ud["xp"] += amount

    new_level = old_level
    while new_level < MAX_LEVEL and ud["xp"] >= xp_for_level(new_level):
        ud["xp"] -= xp_for_level(new_level)
        new_level += 1

    ud["level"] = new_level
    db.save_levels(data)

    if new_level <= old_level:
        return None

    await sync_level_roles(guild, member, new_level)
    if channel:
        await send_level_up_message(member, guild, new_level, channel)
    return (old_level, new_level)


async def send_level_up_message(
    member: discord.Member,
    guild: discord.Guild,
    level: int,
    channel: discord.TextChannel,
) -> None:
    ud = db.levels().get(str(guild.id), {}).get(str(member.id), {"xp": 0, "level": level})
    xp = ud.get("xp", 0)

    is_max = level >= MAX_LEVEL
    needed = xp_for_level(level) if not is_max else 1
    bar = progress_bar(xp, needed)
    pct = int((xp / needed) * 100) if needed else 100

    role_text = ""
    if level in LEVEL_ROLES:
        role = guild.get_role(LEVEL_ROLES[level])
        if role:
            role_name = LEVEL_ROLE_NAMES.get(level, role.name)
            role_text = f"\n**Role unlocked** {role.mention} — *{role_name}*"

    next_ml = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
    next_text = f"Next milestone at level **{next_ml}**" if next_ml else "Maximum level reached!"
    accent = 0xFFD700 if is_max else (0xC3B1E1 if level in LEVEL_ROLES else 0xA8D8EA)
    title = "🏆 Maximum level reached!" if is_max else f"⬆️ Level {level}"

    progress_line = (
        f"`{bar}` **{pct}%**\n`{xp}` / `{needed}` XP toward level `{level + 1}`\n\n-# {next_text}"
        if not is_max
        else f"`{bar}` **{pct}%**\n`{xp}` XP\n\n-# {next_text}"
    )

    await api_send(channel.id, {
        "flags": 32768,
        "components": [
            {
                "type": 17,
                "accent_color": accent,
                "components": [
                    {
                        "type": 9,
                        "components": [
                            {
                                "type": 10,
                                "content": (
                                    f"## {title}\n"
                                    f"{member.mention} just leveled up!"
                                    f"{role_text}"
                                ),
                            }
                        ],
                        "accessory": {
                            "type": 11,
                            "media": {"url": str(member.display_avatar.url)},
                        },
                    },
                    {"type": 14, "divider": True, "spacing": 1},
                    {"type": 10, "content": progress_line},
                ],
            }
        ],
    })
