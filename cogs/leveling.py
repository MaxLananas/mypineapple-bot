from __future__ import annotations
import logging
import random
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands, tasks

import utils.db as db
from utils.api import api_send
from utils.helpers import ts_now
from utils.leveling import add_xp, sync_level_roles, bump_stat
from config import (
    NO_XP_CHANNEL_ID,
    XP_MIN, XP_MAX, XP_COOLDOWN_SECONDS,
    VOICE_XP_INTERVAL, VOICE_XP_AMOUNT,
    REACTION_XP_AMOUNT, REACTION_XP_COOLDOWN,
    ANTISPAM_WINDOW, ANTISPAM_THRESHOLD,
    LEVEL_ROLES, LEVEL_ROLE_NAMES, LEVEL_ROLE_COLORS,
)

log = logging.getLogger(__name__)

_xp_cooldowns: dict[int, float] = {}
_reaction_cooldowns: dict[int, float] = {}
# Anti-spam : file de (contenu, timestamp) par utilisateur.
_recent_messages: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    # ── XP message + anti-spam ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id == NO_XP_CHANNEL_ID:
            return

        now = time.time()
        uid = message.author.id

        # ── Anti-spam copier-coller ──────────────────────────────────────────
        recent = _recent_messages[uid]
        content = message.content.strip()
        if content:
            dupes = sum(1 for c, t in recent if c == content and now - t < ANTISPAM_WINDOW)
            if dupes >= ANTISPAM_THRESHOLD:
                return  # farm neutralisé, pas d'XP
            recent.append((content, now))

        if now - _xp_cooldowns.get(uid, 0) < XP_COOLDOWN_SECONDS:
            return
        _xp_cooldowns[uid] = now

        # Nettoyage périodique des cooldowns.
        if len(_xp_cooldowns) > 5000:
            for k in [k for k, v in _xp_cooldowns.items() if now - v > 3600]:
                _xp_cooldowns.pop(k, None)

        bump_stat(message.guild, message.author, "messages", 1)
        await add_xp(
            guild=message.guild,
            member=message.author,
            amount=random.randint(XP_MIN, XP_MAX),
            channel=message.channel,
        )

    # ── XP réactions ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return
        # Ne récompense que les réactions sur les salons d'annonce (type news).
        if getattr(reaction.message.channel, "type", None) != discord.ChannelType.news:
            return

        now = time.time()
        if now - _reaction_cooldowns.get(user.id, 0) < REACTION_XP_COOLDOWN:
            return
        _reaction_cooldowns[user.id] = now

        member = reaction.message.guild.get_member(user.id)
        if member is None:
            return
        await add_xp(
            guild=reaction.message.guild,
            member=member,
            amount=REACTION_XP_AMOUNT,
        )

    # ── XP vocal (toutes les 10 min) ─────────────────────────────────────────

    @tasks.loop(seconds=VOICE_XP_INTERVAL)
    async def voice_xp_loop(self):
        try:
            for guild in self.bot.guilds:
                afk_id = guild.afk_channel.id if guild.afk_channel else None
                for vc in guild.voice_channels:
                    if vc.id == afk_id:
                        continue
                    for member in vc.members:
                        if member.bot:
                            continue
                        bump_stat(guild, member, "voice_seconds", VOICE_XP_INTERVAL)
                        await add_xp(guild=guild, member=member, amount=VOICE_XP_AMOUNT)
        except Exception as e:
            log.error("voice_xp_loop: %s", e)

    @voice_xp_loop.before_loop
    async def _before_voice_loop(self):
        await self.bot.wait_until_ready()

    # ── Commandes admin ──────────────────────────────────────────────────────

    @app_commands.command(name="levelroles-setup", description="Create missing level roles with the gradient colors.")
    @app_commands.checks.has_permissions(administrator=True)
    async def levelroles_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cfg = db.config()
        db_roles = cfg.setdefault("level_roles", {})

        created, skipped = [], []
        for level in sorted(LEVEL_ROLES):
            role_id = int(db_roles.get(str(level), LEVEL_ROLES[level]))
            role = guild.get_role(role_id)
            if role:
                skipped.append(f"`{level}` {role.mention}")
                continue
            name = LEVEL_ROLE_NAMES.get(level, f"Level {level}")
            # Retire l'emoji de tête pour un nom de rôle propre.
            clean = name.split(" ", 1)[1] if name[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" else name
            color_hex = LEVEL_ROLE_COLORS.get(level, "a0d8ef")
            color = discord.Color(int(color_hex, 16))
            try:
                role = await guild.create_role(name=clean, color=color, reason=f"Level {level} milestone")
            except discord.Forbidden:
                await interaction.followup.send("❌ I lack permission to create roles.", ephemeral=True)
                return
            db_roles[str(level)] = role.id
            created.append(f"`{level}` {role.mention} (#{color_hex})")
        db.save_config(cfg)

        lines = []
        if created:
            lines.append("**Created:**\n" + "\n".join(created))
        if skipped:
            lines.append("**Already exist:**\n" + "\n".join(skipped))
        await interaction.followup.send(
            "✅ Level roles synced!\n\n" + "\n\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="level-rewards", description="List every level role and its threshold.")
    async def level_rewards(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = db.config()
        db_roles = cfg.get("level_roles", {})

        lines = []
        for level in sorted(LEVEL_ROLES):
            role_id = int(db_roles.get(str(level), LEVEL_ROLES[level]))
            role = guild.get_role(role_id)
            mention = role.mention if role else f"*(missing)*"
            lines.append(f"`Lv {level:>3}` — {mention}")

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xC3B1E1,
                    "components": [
                        {"type": 10, "content": f"## 🏆 Level Rewards\nAll milestones (5 → 100)."},
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "\n".join(lines)},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="reward", description="Grant an XP reward to a member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(member="Member to reward.", amount="XP amount.", reason="Reason (optional).")
    async def reward(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 100000],
        reason: str = "Reward",
    ):
        await interaction.response.defer(ephemeral=True)
        result = await add_xp(
            guild=interaction.guild,
            member=member,
            amount=amount,
            channel=interaction.channel,
        )
        ts = ts_now()
        # Carte de récompense publique + confirmation éphémère.
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFD700,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": (
                                        f"## 🎁 Reward Granted\n"
                                        f"{member.mention} received **+{amount} XP**."
                                    ),
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**By** {interaction.user.mention}\n"
                                f"**Reason** {reason}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.followup.send(
            f"✅ Granted `{amount}` XP to {member.mention}.", ephemeral=True
        )

    @app_commands.command(name="xp-reset", description="Reset a member's XP and level.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member to reset.")
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        data = db.levels()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = {"xp": 0, "level": 0}
        db.save_levels(data)
        await sync_level_roles(interaction.guild, member, 0)
        await interaction.followup.send(f"✓ XP reset for {member.mention}.", ephemeral=True)

    @app_commands.command(name="xp-set", description="Force a member's level.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member to update.", level="Target level (0–100).")
    async def xp_set(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        level: app_commands.Range[int, 0, 100],
    ):
        await interaction.response.defer(ephemeral=True)
        data = db.levels()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = {"xp": 0, "level": level}
        db.save_levels(data)
        await sync_level_roles(interaction.guild, member, level)
        await interaction.followup.send(
            f"✓ {member.mention} is now level **{level}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
