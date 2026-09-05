from __future__ import annotations

import discord

import utils.db as db
from utils.emojis import E
from config import SUPPORT_ROLE_ID


def _is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


TICKET_CLOSE_REASONS = {
    "resolved":  ("Resolved",  E.check,     0x57F287),
    "abandoned": ("Abandoned", E.hourglass, 0xFEE75C),
    "duplicate": ("Duplicate", E.file,      0xA8D8EA),
}


def _next_ticket_number() -> int:
    cfg = db.config()
    n = int(cfg.get("ticket_counter", 0)) + 1
    cfg["ticket_counter"] = n
    db.save_config(cfg)
    return n


TICKET_TYPES = {
    "commission": {
        "label":  "Commission",
        "emoji":  "🎨",
        "style":  1,
        "accent": 0x1E90FF,
        "prefix": "commission",
        "header": "# 🌊 MyPineapple Commissions\n## COMMISSION REQUEST\n_Please provide as much detail as possible._",
        "color":  discord.ButtonStyle.primary,
    },
    "bug": {
        "label":  "Bug Report",
        "emoji":  "🐛",
        "style":  2,
        "accent": 0xED4245,
        "prefix": "bug",
        "header": "# 🌊 MyPineapple Bug Reports\n## BUG REPORT\n_Please describe the issue clearly._",
        "color":  discord.ButtonStyle.secondary,
    },
    "partnership": {
        "label":  "Partnership",
        "emoji":  "🤝",
        "style":  2,
        "accent": 0x57F287,
        "prefix": "partner",
        "header": "# 🌊 MyPineapple Partnerships\n## PARTNERSHIP REQUEST\n_Tell us about your project and what you're looking for._",
        "color":  discord.ButtonStyle.secondary,
    },
    "question": {
        "label":  "Question",
        "emoji":  "❓",
        "style":  2,
        "accent": 0xF7CAC9,
        "prefix": "question",
        "header": "# 🌊 MyPineapple Support\n## GENERAL QUESTION\n_Ask us anything!_",
        "color":  discord.ButtonStyle.secondary,
    },
}


def _build_overwrites(guild: discord.Guild, member: discord.Member) -> dict:
    support_role = guild.get_role(SUPPORT_ROLE_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            manage_channels=True, manage_messages=True,
        ),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_messages=True,
        )
    return overwrites


def _is_image_url(url: str) -> bool:
    low = url.lower()
    return (
        "cdn.discordapp.com/attachments" in low
        or any(ext in low for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"))
    )
