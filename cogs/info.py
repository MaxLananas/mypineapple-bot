from __future__ import annotations
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send
from utils.helpers import ts_now
from config import (
    LOGO_URL, DISCORD_INVITE, INSTAGRAM_URL, WEBSITE_URL, YOUTUBE_URL,
    LEVEL_ROLES, LEVEL_ROLE_NAMES,
)

log = logging.getLogger(__name__)

_start_time = time.time()


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="links", description="Display official MyPineapple links.")
    async def links(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x9B8EC4,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": "# 🌊 Official Links\nAll MyPineapple links in one place.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Discord** — {DISCORD_INVITE}\n"
                                f"**Instagram** — {INSTAGRAM_URL}\n"
                                f"**Website** — {WEBSITE_URL}\n"
                                f"**YouTube** — {YOUTUBE_URL}"
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "-# ✦ Stay connected with MyPineapple 🍍"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="serverinfo", description="Display server information.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        ts = int(guild.created_at.timestamp())
        bots = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots
        # Sans l'intent "presences", le statut est inconnu : on le signale.
        if self.bot.intents.presences:
            online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
            online_line = f"**Online** `{online}`\n"
        else:
            online_line = ""

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xA8D8EA,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": f"## {guild.name}\nServer information & statistics."}
                            ],
                            "accessory": {
                                "type": 11,
                                "media": {"url": str(guild.icon.url) if guild.icon else LOGO_URL},
                            },
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Owner** <@{guild.owner_id}>\n"
                                f"**Created** <t:{ts}:D>\n"
                                f"**Members** `{guild.member_count}` total · `{humans}` humans · `{bots}` bots\n"
                                f"{online_line}"
                                f"**Channels** `{len(guild.text_channels)}` text · `{len(guild.voice_channels)}` voice\n"
                                f"**Roles** `{len(guild.roles)}`\n"
                                f"**Boosts** `{guild.premium_subscription_count}` (Level `{guild.premium_tier}`)"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="userinfo", description="Display information about a member.")
    @app_commands.describe(member="The member (default: yourself).")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        joined = int(target.joined_at.timestamp()) if target.joined_at else 0
        created = int(target.created_at.timestamp())
        roles = [r.mention for r in reversed(target.roles) if r.name != "@everyone"]
        rt = " ".join(roles[:8]) + (f" +{len(roles)-8}" if len(roles) > 8 else "") if roles else "None"

        ud = db.levels().get(str(interaction.guild_id), {}).get(str(target.id), {"xp": 0, "level": 0})
        level = ud["level"]
        role_name = None
        for ms in sorted(LEVEL_ROLES, reverse=True):
            if level >= ms:
                role_name = LEVEL_ROLE_NAMES.get(ms)
                break

        level_line = f"**Level** `{level}` · **XP** `{ud['xp']}`"
        if role_name:
            level_line += f" · {role_name}"

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xC3B1E1,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## {target.display_name}\n`{target}` · `{target.id}`",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(target.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Account created** <t:{created}:D>\n"
                                f"**Joined server** <t:{joined}:D>\n"
                                f"{level_line}\n"
                                f"**Roles** {rt}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="avatar", description="Display a member's avatar.")
    @app_commands.describe(member="The member (default: yourself).")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xA8D8EA,
                    "components": [
                        {"type": 10, "content": f"## {target.display_name}'s Avatar"},
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 12,
                            "items": [{"media": {"url": str(target.display_avatar.with_size(1024).url)}}],
                        },
                        {
                            "type": 10,
                            "content": f"-# [Open full resolution]({target.display_avatar.with_size(4096).url})",
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction):
        ws_ms = round(self.bot.latency * 1000)
        colour = 0x57F287 if ws_ms < 100 else (0xFEE75C if ws_ms < 200 else 0xED4245)
        icon = "🟢" if ws_ms < 100 else ("🟡" if ws_ms < 200 else "🔴")
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": colour,
                    "components": [
                        {"type": 10, "content": f"## {icon} Pong!\n**WebSocket** `{ws_ms}ms`"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="botinfo", description="Bot statistics.")
    async def botinfo(self, interaction: discord.Interaction):
        import sys, platform
        uptime_s = int(time.time() - _start_time)
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        uptime = f"{h}h {m}m {s}s"
        guilds = len(self.bot.guilds)
        members = sum(g.member_count for g in self.bot.guilds)
        cmds = len(self.bot.tree.get_commands())

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x9B8EC4,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": f"## 🤖 {self.bot.user.name}\nReal-time statistics."}
                            ],
                            "accessory": {"type": 11, "media": {"url": str(self.bot.user.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Uptime** `{uptime}`\n"
                                f"**Servers** `{guilds}`\n"
                                f"**Members** `{members}`\n"
                                f"**Commands** `{cmds}`\n"
                                f"**Python** `{sys.version.split()[0]}`\n"
                                f"**discord.py** `{discord.__version__}`\n"
                                f"**Platform** `{platform.system()} {platform.release()}`"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="rank", description="Check your level and XP.")
    @app_commands.describe(member="The member to check (default: yourself).")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        data = db.levels()
        guild_id = str(interaction.guild_id)
        user_id = str(target.id)

        ud = data.get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})
        level = ud["level"]
        xp = ud["xp"]
        from utils.helpers import xp_for_level, progress_bar
        needed = xp_for_level(level)
        bar = progress_bar(xp, needed)
        pct = int((xp / needed) * 100) if needed else 0

        all_u = data.get(guild_id, {})
        sorted_ = sorted(all_u.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
        rank_n = next((i + 1 for i, (uid, _) in enumerate(sorted_) if uid == user_id), "?")

        role_name = None
        for ms in sorted(LEVEL_ROLES, reverse=True):
            if level >= ms:
                role_name = LEVEL_ROLE_NAMES.get(ms)
                break

        next_ml = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
        ml_text = f"Next role at level **{next_ml}**" if next_ml else "All roles unlocked! 🍍"
        role_line = f"**Role** {role_name}\n" if role_name else ""

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xA8D8EA,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## {target.display_name}\nLevel `{level}` · Rank `#{rank_n}`",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(target.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"{role_line}"
                                f"`{bar}` **{pct}%**\n"
                                f"`{xp}` / `{needed}` XP\n\n"
                                f"-# {ml_text}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="leaderboard", description="Show the top 10 members by level.")
    async def leaderboard(self, interaction: discord.Interaction):
        data = db.levels()
        guild_id = str(interaction.guild_id)
        all_u = data.get(guild_id, {})

        if not all_u:
            await interaction.response.send_message("No data yet.", ephemeral=True)
            return

        sorted_ = sorted(all_u.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, ud) in enumerate(sorted_):
            badge = medals[i] if i < 3 else f"`#{i+1}`"
            m = interaction.guild.get_member(int(uid))
            name = m.display_name if m else f"User {uid}"
            role_name = None
            for ms in sorted(LEVEL_ROLES, reverse=True):
                if ud["level"] >= ms:
                    role_name = LEVEL_ROLE_NAMES.get(ms)
                    break
            suffix = f" · *{role_name}*" if role_name else ""
            lines.append(f"{badge} **{name}** — Level `{ud['level']}`{suffix}")

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xF7CAC9,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": "# 🏆 Leaderboard\nTop 10 members by level."}
                            ],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "\n".join(lines)},
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "-# Keep chatting to climb the ranks. 🍍"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))