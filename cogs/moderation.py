from __future__ import annotations
import logging
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send, MENTIONS_ALL
from utils.helpers import ts_now

log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"(\d+)\s*([smhdjw])", re.IGNORECASE)
_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "j": 86400, "w": 604800}


def parse_duration(text: str) -> timedelta | None:
    total = 0
    for amount, unit in _DURATION_RE.findall(text):
        total += int(amount) * _MULTIPLIERS[unit.lower()]
    return timedelta(seconds=total) if total else None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(member="Member to ban.", reason="Reason.", delete_days="Days of messages to delete (0–7).")
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided.",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("You cannot ban this member.", ephemeral=True)
            return
        try:
            await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=delete_days)
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission to ban this member.", ephemeral=True)
            return

        ts = ts_now()
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xED4245,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## 🔨 Member Banned\n**{member}** has been permanently removed.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**User** {member.mention} (`{member.id}`)\n"
                                f"**Moderator** {interaction.user.mention}\n"
                                f"**Reason** {reason}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.describe(member="Member to kick.", reason="Reason.")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided.",
    ):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("You cannot kick this member.", ephemeral=True)
            return
        try:
            await member.kick(reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission to kick this member.", ephemeral=True)
            return

        ts = ts_now()
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xE67E22,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## 👢 Member Kicked\n**{member}** has been removed.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**User** {member.mention} (`{member.id}`)\n"
                                f"**Moderator** {interaction.user.mention}\n"
                                f"**Reason** {reason}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="unban", description="Unban a user by ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(user_id="The Discord user ID.", reason="Reason.")
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str = "No reason provided.",
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user} — {reason}")
        except ValueError:
            await interaction.followup.send("Invalid ID.", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.followup.send("This user is not banned.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send("I lack permission to unban.", ephemeral=True)
            return

        ts = ts_now()
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
                                {
                                    "type": 10,
                                    "content": f"## ✅ Member Unbanned\n**{user}** can return to the server.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(user.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**User** {user.mention} (`{user.id}`)\n"
                                f"**Moderator** {interaction.user.mention}\n"
                                f"**Reason** {reason}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="banlist", description="Show the list of banned members.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def banlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bans = [entry async for entry in interaction.guild.bans(limit=50)]
        if not bans:
            await interaction.followup.send("No banned members.", ephemeral=True)
            return

        lines = []
        for entry in bans[:25]:
            reason = entry.reason or "No reason"
            lines.append(f"**{entry.user}** (`{entry.user.id}`) — *{reason[:60]}*")

        total = len(bans)
        icon_url = str(interaction.guild.icon.url) if interaction.guild.icon else ""

        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xED4245,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": f"## 🔨 Ban List\n{total} member(s) banned."}
                            ],
                            "accessory": {"type": 11, "media": {"url": icon_url}} if icon_url else {"type": 11, "media": {"url": "https://i.ibb.co/WWbL1v1k/7391989548e4747ad18756fa467b74da.webp"}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "\n".join(lines)},
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": f"-# Showing {min(25, total)}/{total} bans."},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="mute", description="Timeout a member (e.g. 10m, 2h, 7d).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member.", duration="Duration (e.g. 10m, 2h, 1d).", reason="Reason.")
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str = "No reason provided.",
    ):
        delta = parse_duration(duration)
        if not delta:
            await interaction.response.send_message("Invalid duration. Examples: `10m`, `2h`, `7d`.", ephemeral=True)
            return
        if delta > timedelta(days=28):
            await interaction.response.send_message("Maximum duration: 28 days.", ephemeral=True)
            return
        try:
            until = datetime.now(timezone.utc) + delta
            await member.timeout(until, reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission.", ephemeral=True)
            return

        ts = ts_now()
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFA500,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## 🔇 Member Muted\n**{member}** has been silenced.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**User** {member.mention} (`{member.id}`)\n"
                                f"**Duration** `{duration}`\n"
                                f"**Expires** <t:{int(until.timestamp())}:F>\n"
                                f"**Moderator** {interaction.user.mention}\n"
                                f"**Reason** {reason}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="unmute", description="Remove a member's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member.", reason="Reason.")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        try:
            await member.timeout(None, reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission.", ephemeral=True)
            return
        await interaction.response.send_message(f"✓ Timeout removed for {member.mention}.", ephemeral=True)

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member.", reason="Reason for the warning.")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        data = db.warns()
        guild_id = str(interaction.guild_id)
        user_id = str(member.id)

        warns_list = data.setdefault(guild_id, {}).setdefault(user_id, [])
        warns_list.append({
            "reason": reason,
            "by": str(interaction.user.id),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        db.save_warns(data)

        count = len(warns_list)
        ts = ts_now()

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFCC00,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## ⚠️ Warning `#{count}`\n{member.mention} received a warning.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Moderator** {interaction.user.mention}\n"
                                f"**Reason** {reason}\n"
                                f"**Total warns** `{count}`\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

        if count >= 5:
            try:
                await member.ban(reason="5 accumulated warnings")
            except Exception:
                pass
        elif count >= 3:
            try:
                await member.kick(reason="3 accumulated warnings")
            except Exception:
                pass

    @app_commands.command(name="warnings", description="View a member's warnings.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member to inspect.")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        data = db.warns()
        warns_list = data.get(str(interaction.guild_id), {}).get(str(member.id), [])

        if not warns_list:
            await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
            return

        lines = []
        for i, w in enumerate(warns_list, 1):
            dt = datetime.fromisoformat(w["at"])
            lines.append(f"`#{i}` <t:{int(dt.timestamp())}:d> — {w['reason']}")

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFCC00,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## ⚠️ Warnings — {member.display_name}\n`{len(warns_list)}` warning(s) total.",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(member.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "\n".join(lines)},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member.")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        data = db.warns()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = []
        db.save_warns(data)
        await interaction.response.send_message(f"✓ Warnings cleared for {member.mention}.", ephemeral=True)

    @app_commands.command(name="purge", description="Delete messages in bulk.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages (1–100).",
        member="Only delete messages from this member.",
        keyword="Only delete messages containing this keyword.",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        member: discord.Member | None = None,
        keyword: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        kw = keyword.lower() if keyword else None

        def check(m: discord.Message) -> bool:
            if m.pinned:  # Garde les messages épinglés.
                return False
            if member is not None and m.author.id != member.id:
                return False
            if kw is not None and kw not in m.content.lower():
                return False
            return True

        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        old_count = 0

        try:
            deleted = await interaction.channel.purge(limit=amount, check=check)
        except discord.HTTPException:
            deleted = []
            async for m in interaction.channel.history(limit=amount):
                if check(m):
                    if m.created_at < cutoff:
                        old_count += 1
                        continue
                    try:
                        await m.delete()
                        deleted.append(m)
                    except discord.HTTPException:
                        old_count += 1

        msg = f"✓ Deleted `{len(deleted)}` message(s)."
        if old_count:
            msg += f"\n⚠️ `{old_count}` message(s) skipped (pinned or older than 14 days)."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="slowmode", description="Set the slowmode of a channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Seconds (0 = disabled, max 21600).")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = f"✓ Slowmode **disabled**." if seconds == 0 else f"✓ Slowmode set to **{seconds}s**."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="lock", description="Lock a channel or thread.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            await channel.edit(locked=True)
        else:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock a channel or thread.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            await channel.edit(locked=False)
        else:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)

    @app_commands.command(name="announce", description="Post a styled announcement.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Target channel.",
        title="Announcement title.",
        message="Content.",
        ping="Mention (@here, @everyone, or role ID).",
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
        ping: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        ts = ts_now()

        ping_text = ""
        if ping:
            p = ping.strip()
            if p in ("@here", "@everyone"):
                ping_text = p
            elif p.isdigit():
                role = interaction.guild.get_role(int(p))
                if role:
                    ping_text = role.mention

        components = [
            {
                "type": 17,
                "accent_color": 0x9B8EC4,
                "components": [
                    {
                        "type": 9,
                        "components": [
                            {"type": 10, "content": f"# 📢 {title}"},
                        ],
                        "accessory": {
                            "type": 11,
                            "media": {
                                "url": str(interaction.guild.icon.url)
                                if interaction.guild.icon
                                else "https://i.ibb.co/WWbL1v1k/7391989548e4747ad18756fa467b74da.webp"
                            },
                        },
                    },
                    {"type": 14, "divider": True, "spacing": 1},
                    {"type": 10, "content": message},
                    {"type": 14, "divider": True, "spacing": 1},
                    {
                        "type": 10,
                        "content": f"-# Announcement by {interaction.user.mention} · <t:{ts}:F>",
                    },
                ],
            }
        ]

        if ping_text:
            ping_components = [{"type": 10, "content": ping_text}] + components[0]["components"]
            components[0]["components"] = ping_components

        status, resp = await api_send(
            channel.id,
            {"flags": 32768, "components": components},
            allowed_mentions=MENTIONS_ALL if ping_text else None,
        )
        msg = f"✓ Announcement posted in {channel.mention}!" if status in (200, 201) else f"✗ Error `{status}`"
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))