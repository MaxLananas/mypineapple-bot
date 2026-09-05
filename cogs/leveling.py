from __future__ import annotations
import random
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.leveling import add_xp, sync_level_roles
from config import NO_XP_CHANNEL_ID

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

        now = time.time()
        uid = message.author.id

        if now - _xp_cooldowns.get(uid, 0) < 60:
            return
        _xp_cooldowns[uid] = now

        # Nettoyage périodique du dict de cooldown (évite de grossir indéfiniment)
        if len(_xp_cooldowns) > 5000:
            for k in [k for k, v in _xp_cooldowns.items() if now - v > 3600]:
                _xp_cooldowns.pop(k, None)

        await add_xp(
            guild=message.guild,
            member=message.author,
            amount=random.randint(15, 25),
            channel=message.channel,
        )

    @app_commands.command(name="xp-reset", description="Reset a member's XP and level.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member to reset.")
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        data = db.levels()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = {"xp": 0, "level": 0}
        db.save_levels(data)
        await sync_level_roles(interaction.guild, member, 0)
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
        await sync_level_roles(interaction.guild, member, level)
        await interaction.response.send_message(
            f"✓ {member.mention} is now level **{level}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
