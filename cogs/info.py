from __future__ import annotations
import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send, get_session
from utils.helpers import xp_needed, MAX_LEVEL
from utils.emojis import E
from utils.leveling import level_roles, level_role_name, daily_xp_history
from utils.images import generate_rank_card
from utils.graphs import generate_xp_graph
from config import (
    LOGO_URL, DISCORD_INVITE, INSTAGRAM_URL, WEBSITE_URL, YOUTUBE_URL,
)

log = logging.getLogger(__name__)

_start_time = time.time()


def _rank_data(interaction: discord.Interaction, target: discord.Member) -> dict:
    """Compute level/XP/rank/role for a member."""
    data = db.levels()
    guild_id = str(interaction.guild_id)
    user_id = str(target.id)

    ud = data.get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})
    level = ud["level"]
    xp = ud["xp"]
    needed = xp_needed(level)

    all_u = data.get(guild_id, {})
    sorted_ = sorted(all_u.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
    rank_n = next((i + 1 for i, (uid, _) in enumerate(sorted_) if uid == user_id), 1)

    role_name = None
    for ms in sorted(level_roles(), reverse=True):
        if level >= ms:
            role_name = level_role_name(ms)
            break

    return {
        "level": level, "xp": xp, "needed": needed, "rank": rank_n,
        "role_name": role_name, "is_max": level >= MAX_LEVEL,
    }


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
        online = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
        online_line = f"**Online** `{online}`\n"

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
        for ms in sorted(level_roles(), reverse=True):
            if level >= ms:
                role_name = level_role_name(ms)
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

    @app_commands.command(name="ping", description="Check bot, API and database latency.")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ws_ms = round(self.bot.latency * 1000)

        # API latency: time a trivial REST round-trip (own user fetch).
        api_start = time.perf_counter()
        try:
            await self.bot.fetch_user(self.bot.user.id)
            api_ms = round((time.perf_counter() - api_start) * 1000)
        except Exception:
            api_ms = -1

        # Database latency (healthcheck).
        db_ms = round(await db.ping(), 1)

        def _badge(ms: float) -> str:
            if ms < 0:
                return E.dot_red
            return E.dot_green if ms < 100 else (E.dot_yellow if ms < 250 else E.dot_red)

        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x57F287,
                    "components": [
                        {"type": 10, "content": f"## {E.dot_green} Pong!\nLatency breakdown."},
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"{_badge(ws_ms)} **WebSocket** `{ws_ms}ms`\n"
                                f"{_badge(api_ms)} **API** `{api_ms}ms`\n"
                                f"{_badge(db_ms)} **Database** `{db_ms}ms`"
                            ),
                        },
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

    @app_commands.command(name="rank", description="Show your rank as a styled image card.")
    @app_commands.describe(member="The member to check (default: yourself).")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        await interaction.response.defer(ephemeral=True)

        rd = _rank_data(interaction, target)
        try:
            png = await generate_rank_card(
                get_session(),
                avatar_url=str(target.display_avatar.with_size(256).url),
                username=target.display_name,
                level=rd["level"],
                xp=rd["xp"],
                needed=rd["needed"],
                rank=rd["rank"],
                role_name=rd["role_name"],
                is_max=rd["is_max"],
            )
            await interaction.channel.send(
                file=discord.File(io.BytesIO(png), filename=f"rank-{target.id}.png")
            )
            await interaction.delete_original_response()
        except Exception as e:
            log.error("rank card: %s", e)
            await interaction.followup.send("Couldn't generate the rank card.", ephemeral=True)

    @app_commands.command(name="stats", description="Your activity stats with an XP graph.")
    @app_commands.describe(member="Member to inspect (default: yourself).")
    async def stats(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target   = member or interaction.user
        guild_id = str(interaction.guild_id)
        user_id  = str(target.id)

        st = db.stats().get(guild_id, {}).get(user_id, {})
        messages = st.get("messages", 0)
        xp_total = st.get("xp_total", 0)
        voice_s  = st.get("voice_seconds", 0)

        h, rem = divmod(voice_s, 3600)
        m, s = divmod(rem, 60)
        voice_text = f"{h}h {m}m {s}s" if voice_s else "0m"

        ud    = db.levels().get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})
        level = ud["level"]
        xp    = ud["xp"]

        await interaction.response.defer(ephemeral=True)

        # XP graph over the last 7 days.
        try:
            history = daily_xp_history(interaction.guild_id, target.id)
            graph = generate_xp_graph(username=target.display_name, daily_xp=history)
            await interaction.channel.send(
                file=discord.File(io.BytesIO(graph), filename=f"stats-{target.id}.png")
            )
        except Exception as e:
            log.error("stats graph: %s", e)

        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x57F287,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": f"## {E.chart} {target.display_name}'s Stats\n`{target}`"}
                            ],
                            "accessory": {"type": 11, "media": {"url": str(target.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"{E.pencil} **Messages** `{messages}`\n"
                                f"{E.gem} **XP earned** `{xp_total}`\n"
                                f"{E.mic} **Voice time** `{voice_text}`\n"
                                f"{E.star} **Level** `{level}` · `{xp}` XP"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="emojis", description="List all custom server emojis.")
    @app_commands.checks.has_permissions(administrator=True)
    async def emojis_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        emojis = sorted(interaction.guild.emojis, key=lambda x: x.name)
        if not emojis:
            await interaction.followup.send("No custom emojis on this server.", ephemeral=True)
            return

        lines = [f"{e} `<:{e.name}:{e.id}>`  `:{e.name}:`" for e in emojis]

        # Pagination : 15 lignes par page, toutes envoyées en éphémère.
        per_page = 15
        pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
        for idx, page in enumerate(pages, 1):
            content = f"## 🎨 Custom Emojis — {idx}/{len(pages)}\n" + "\n".join(page)
            await interaction.followup.send(content, ephemeral=True)

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
            for ms in sorted(level_roles(), reverse=True):
                if ud["level"] >= ms:
                    role_name = level_role_name(ms)
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