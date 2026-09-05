from __future__ import annotations
import random
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send
from utils.helpers import xp_for_level, progress_bar, safe_add_role
from config import LEVEL_ROLES, LEVEL_ROLE_NAMES, NO_XP_CHANNEL_ID

log = logging.getLogger(__name__)

_xp_cooldowns: dict[int, float] = {}


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id == NO_XP_CHANNEL_ID:
            return

        now = datetime.now(timezone.utc).timestamp()
        uid = message.author.id

        if now - _xp_cooldowns.get(uid, 0) < 60:
            return
        _xp_cooldowns[uid] = now

        data     = db.levels()
        guild_id = str(message.guild.id)
        user_id  = str(uid)

        ud = (
            data
            .setdefault(guild_id, {})
            .setdefault(user_id, {"xp": 0, "level": 0})
        )
        ud["xp"] += random.randint(15, 25)

        leveled_up = False
        new_level  = ud["level"]

        while ud["level"] < 100 and ud["xp"] >= xp_for_level(ud["level"]):
            ud["xp"]    -= xp_for_level(ud["level"])
            ud["level"] += 1
            leveled_up   = True
            new_level    = ud["level"]

        db.save_levels(data)

        if leveled_up:
            await self._handle_level_up(message.author, message.guild, new_level, message.channel)

    async def _handle_level_up(
        self,
        member:  discord.Member,
        guild:   discord.Guild,
        level:   int,
        channel: discord.TextChannel,
    ):
        ud     = db.levels().get(str(guild.id), {}).get(str(member.id), {"xp": 0, "level": level})
        xp     = ud["xp"]
        needed = xp_for_level(level)
        bar    = progress_bar(xp, needed)
        pct    = int((xp / needed) * 100) if needed else 0

        role_text = ""
        if level in LEVEL_ROLES:
            role = guild.get_role(LEVEL_ROLES[level])
            if role:
                await safe_add_role(member, role, reason=f"Level {level}")
                role_name = LEVEL_ROLE_NAMES.get(level, role.name)
                role_text = f"\n**Role unlocked** {role.mention} — *{role_name}*"

        next_ml   = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
        next_text = f"Next milestone at level **{next_ml}**" if next_ml else "Maximum level reached!"
        accent    = 0xFFD700 if level == 100 else (0xC3B1E1 if level in LEVEL_ROLES else 0xA8D8EA)
        title     = "🏆 Maximum level reached!" if level == 100 else f"⬆️ Level {level}"

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
                        {
                            "type": 10,
                            "content": (
                                f"`{bar}` **{pct}%**\n"
                                f"`{xp}` / `{needed}` XP toward level `{level + 1}`\n\n"
                                f"-# {next_text}"
                            ),
                        },
                    ],
                }
            ],
        })

    @app_commands.command(name="xp-reset", description="Reset a member's XP and level.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member to reset.")
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        data = db.levels()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = {"xp": 0, "level": 0}
        db.save_levels(data)
        await interaction.response.send_message(f"✓ XP reset for {member.mention}.", ephemeral=True)

    @app_commands.command(name="xp-set", description="Force a member's level.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member to update.", level="Target level (0–100).")
    async def xp_set(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        level: app_commands.Range[int, 0, 100],
    ):
        data = db.levels()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = {"xp": 0, "level": level}
        db.save_levels(data)
        await interaction.response.send_message(
            f"✓ {member.mention} is now level **{level}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))