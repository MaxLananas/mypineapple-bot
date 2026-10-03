from __future__ import annotations
import logging
import random

import discord
from discord.ext import commands

from utils.api import api_send
from utils.helpers import ts_now, safe_add_role
from config import AUTOROLE_ID, WELCOME_CHANNEL_ID, PORTFOLIO_FILES, RELEASE_BASE, CREDITS

log = logging.getLogger(__name__)

# Nom de fallback si l'ID ne trouve rien (partie du nom suffit)
WELCOME_CHANNEL_NAME_FALLBACK = "arrivals"

WELCOME_MESSAGES = [
    ("🌊", "washed ashore on our island like a bottle at sea"),
    ("🏝️", "just landed on MyPineapple Island"),
    ("🐋", "surfaced from the deep — welcome aboard"),
    ("⛵", "boarded our ship. All sails up"),
    ("🪸", "found their way to our favourite coral reef"),
    ("⚓", "anchored in our harbour. Welcome aboard"),
    ("🦑", "emerged from the abyss"),
    ("🍍", "floated here on a giant pineapple"),
    ("🌺", "bloomed on our tropical shores"),
    ("🐠", "swam through the reef and found paradise"),
    ("🌅", "arrived with the tide at golden hour"),
    ("🦀", "scuttled onto the beach — don't be shy"),
    ("🐬", "leapt into the lagoon head-first"),
    ("🌴", "got lost in the palm trees and decided to stay"),
]

COMMISSION_CHANNEL = "https://discord.com/channels/1518717924607787199/1518727130681180330"


def _resolve_channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel | None:
    """
    Cherche d'abord par ID, puis par nom (fallback 'arrivals').
    Logue clairement ce qui se passe.
    """
    ch = guild.get_channel(channel_id)
    if ch is not None:
        log.info("Welcome channel found by ID: %s (%d)", ch.name, ch.id)
        return ch

    # Fallback : cherche un channel dont le nom contient "arrivals"
    log.warning(
        "Welcome channel ID %d not found — trying fallback by name '%s'",
        channel_id,
        WELCOME_CHANNEL_NAME_FALLBACK,
    )
    for c in guild.text_channels:
        if WELCOME_CHANNEL_NAME_FALLBACK in c.name.lower():
            log.info("Welcome channel found by name fallback: %s (%d)", c.name, c.id)
            return c

    log.error(
        "Welcome channel introuvable par ID ou nom — channels dispo: %s",
        [f"{c.name}({c.id})" for c in guild.text_channels],
    )
    return None


def _resolve_autorole(guild: discord.Guild, role_id: int) -> discord.Role | None:
    """
    Cherche le rôle par ID. Si absent, logue tous les rôles pour aider au debug.
    """
    role = guild.get_role(role_id)
    if role is not None:
        return role

    log.error(
        "Auto-role ID %d introuvable — rôles dispo: %s",
        role_id,
        [f"{r.name}({r.id})" for r in guild.roles],
    )
    return None


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log.info("on_member_join fired for %s in guild %s", member, member.guild.name)

        guild = member.guild

        # ── Auto-role ──────────────────────────────────────────────
        role = _resolve_autorole(guild, AUTOROLE_ID)
        if role:
            await safe_add_role(member, role, reason="Auto-role on join")
        # (l'erreur est déjà loguée dans _resolve_autorole)

        # ── Welcome channel ────────────────────────────────────────
        welcome_ch = _resolve_channel(guild, WELCOME_CHANNEL_ID)
        if welcome_ch is None:
            return

        # ── Contenu du message ─────────────────────────────────────
        build_entry  = random.choice(PORTFOLIO_FILES)
        build_url    = RELEASE_BASE + build_entry["name"]
        credit_key   = build_entry.get("credit")
        credit_info  = CREDITS.get(credit_key) if credit_key else None

        if credit_info:
            url = credit_info.get("url")
            build_caption = (
                f"-# Build in collaboration with [{credit_info['label']}]({url})"
                if url
                else f"-# Build in collaboration with **{credit_info['label']}**"
            )
        else:
            build_caption = None

        emoji, phrase = random.choice(WELCOME_MESSAGES)
        member_cnt    = guild.member_count
        created_ts    = int(member.created_at.timestamp())
        join_ts       = ts_now()

        inner_components = [
            {
                "type": 12,
                "items": [
                    {
                        "media": {"url": build_url},
                        "description": "MyPineapple build showcase",
                        "spoiler": False,
                    }
                ],
            },
        ]

        if build_caption:
            inner_components.append({"type": 10, "content": build_caption})

        inner_components += [
            {"type": 14, "divider": True, "spacing": 1},
            {
                "type": 9,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"## {emoji} Welcome, {member.display_name}!\n"
                            f"*{member.mention} {phrase}.*"
                        ),
                    }
                ],
                "accessory": {
                    "type": 11,
                    "media": {"url": str(member.display_avatar.url)},
                },
            },
            {"type": 14, "divider": True, "spacing": 1},
            {
                "type": 10,
                "content": (
                    f"You are the **{member_cnt}th** member of the server.\n"
                    f"**Account created** <t:{created_ts}:R>\n"
                    f"**Joined** <t:{join_ts}:F>\n\n"
                    f"📋 Check out our [commissions channel]({COMMISSION_CHANNEL}) to order a build!"
                ),
            },
        ]

        payload = {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x1E90FF,
                    "components": inner_components,
                }
            ],
        }

        status, resp = await api_send(welcome_ch.id, payload)
        if status not in (200, 201):
            log.error("Welcome message failed: %s %s", status, resp)
        else:
            log.info("Welcome message sent for %s in #%s", member, welcome_ch.name)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))