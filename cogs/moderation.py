from __future__ import annotations
import logging
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
import utils.loghub as loghub
from utils.api import api_send, MENTIONS_ALL
from utils.helpers import ts_now, parse_iso
from utils.antispam import process_message
from utils import ui

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Intelligent anti-spam: escalating mutes for repetitive/rapid spam.
        try:
            await process_message(message)
        except Exception as e:
            log.error("antispam on_message: %s", e)

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
        # ACK immédiat : member.ban() est un appel REST qui peut dépasser la
        # fenêtre de 3 s → sinon "Unknown interaction".
        await interaction.response.defer(ephemeral=True)
        reason = reason[:500]  # option slash jusqu'à 6000 car. → 400 côté Discord

        if member.top_role >= interaction.user.top_role:
            await ui.send(interaction, ui.error_card(
                "Ban not applied",
                "You cannot ban a member with an equal or higher role.",
            ), ephemeral=True)
            return
        try:
            await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=delete_days)
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Ban failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return

        ts = ts_now()
        await ui.send_raw(interaction, {
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

        await loghub.mod_action(
            interaction.guild, "Bannissement", member, interaction.user,
            reason=reason, extra=f"**Messages supprimés** `{delete_days} j`",
            color=0xED4245, thumbnail=str(member.display_avatar.url),
        )

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.describe(member="Member to kick.", reason="Reason.")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided.",
    ):
        # ACK immédiat (member.kick() est un appel REST).
        await interaction.response.defer(ephemeral=True)
        reason = reason[:500]

        if member.top_role >= interaction.user.top_role:
            await ui.send(interaction, ui.error_card(
                "Kick not applied",
                "You cannot kick a member with an equal or higher role.",
            ), ephemeral=True)
            return
        try:
            await member.kick(reason=f"{interaction.user} — {reason}")
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Kick failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return

        ts = ts_now()
        await ui.send_raw(interaction, {
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

        await loghub.mod_action(
            interaction.guild, "Expulsion", member, interaction.user,
            reason=reason, color=0xE67E22, thumbnail=str(member.display_avatar.url),
        )

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
            await ui.send(interaction, ui.error_card(
                "Invalid ID", "Give me a numeric Discord user ID, like `123456789012345678`."
            ), ephemeral=True)
            return
        except discord.NotFound:
            await ui.send(interaction, ui.warn_card(
                "Not banned", "That user is not on the ban list."
            ), ephemeral=True)
            return
        except discord.Forbidden:
            await ui.send(interaction, ui.error_card(
                "Missing permission", "I need the **Ban Members** permission to do that."
            ), ephemeral=True)
            return

        ts = ts_now()
        await ui.send_raw(interaction, {
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Débannissement", user, interaction.user,
            reason=reason, color=0x57F287, thumbnail=str(user.display_avatar.url),
        )

    @app_commands.command(name="banlist", description="Show the list of banned members.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def banlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bans = [entry async for entry in interaction.guild.bans(limit=50)]
        if not bans:
            await ui.send(interaction, ui.ok_card(
                "Nobody is banned", "The ban list is empty — clean slate! 🍍"
            ), ephemeral=True)
            return

        lines = []
        for entry in bans[:25]:
            reason = entry.reason or "No reason"
            lines.append(f"**{entry.user}** (`{entry.user.id}`) — *{reason[:60]}*")

        total = len(bans)
        icon_url = str(interaction.guild.icon.url) if interaction.guild.icon else ""

        await ui.send_raw(interaction, {
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

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
        # ACK immédiat : member.timeout() est un appel REST.
        await interaction.response.defer(ephemeral=True)
        reason = reason[:500]

        delta = parse_duration(duration)
        if not delta:
            await ui.send(interaction, ui.warn_card(
                "Invalid duration", "Try something like `10m`, `2h` or `7d`."
            ), ephemeral=True)
            return
        if delta > timedelta(days=28):
            await ui.send(interaction, ui.warn_card(
                "Too long", "Discord timeouts are capped at **28 days**."
            ), ephemeral=True)
            return
        try:
            until = datetime.now(timezone.utc) + delta
            await member.timeout(until, reason=f"{interaction.user} — {reason}")
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Timeout failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return

        await ui.send_raw(interaction, {
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

        await loghub.mod_action(
            interaction.guild, "Timeout appliqué", member, interaction.user,
            reason=reason,
            extra=f"**Durée** `{duration}` · **Expire** <t:{int(until.timestamp())}:F>",
            color=0xFFA500, thumbnail=str(member.display_avatar.url),
        )

    @app_commands.command(name="unmute", description="Remove a member's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member.", reason="Reason.")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(None, reason=f"{interaction.user} — {reason}")
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Unmute failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return
        await ui.send(interaction, ui.ok_card(
            "Timeout removed", f"{member.mention} can speak again."
        ), ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Timeout retiré", member, interaction.user,
            reason=reason, color=0x57F287, thumbnail=str(member.display_avatar.url),
        )

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="Member.", reason="Reason for the warning.")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        reason = reason[:1000]  # une option slash peut monter à 6000 car. → 400 côté Discord
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
        await ui.send_raw(interaction, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": ui.ACCENT_MOD_WARN,
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

        await loghub.mod_action(
            interaction.guild, f"Avertissement `#{count}`", member, interaction.user,
            reason=reason, color=0xFFCC00, thumbnail=str(member.display_avatar.url),
        )

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
            await ui.send(interaction, ui.ok_card(
                "No warnings", f"{member.mention} has a clean record. ✨"
            ), ephemeral=True)
            return

        # On n'affiche que les 15 dernières avec des raisons bornées : un membre
        # très warn faisait dépasser la limite de 4000 caractères par bloc.
        shown = warns_list[-15:]
        offset = len(warns_list) - len(shown)
        lines = []
        for i, w in enumerate(shown, offset + 1):
            dt    = parse_iso(w.get("at"))
            stamp = f"<t:{int(dt.timestamp())}:d>" if dt else "`date inconnue`"
            reason = str(w.get("reason", "No reason provided"))[:150]
            lines.append(f"`#{i}` {stamp} — {reason}")
        if offset:
            lines.insert(0, f"-# … {offset} earlier warning(s) hidden")

        await interaction.response.defer(ephemeral=True)
        await ui.send_raw(interaction, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": ui.ACCENT_MOD_WARN,
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
        }, accent=ui.ACCENT_MOD, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Member.")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        data = db.warns()
        data.setdefault(str(interaction.guild_id), {})[str(member.id)] = []
        db.save_warns(data)
        await ui.send(interaction, ui.ok_card(
            "Warnings cleared", f"{member.mention} starts over with a clean record."
        ), ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Avertissements effacés", member, interaction.user,
            color=0x95A5A6, thumbnail=str(member.display_avatar.url),
        )

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

        await loghub.mod_action(
            interaction.guild, "Purge", interaction.channel, interaction.user,
            reason=f"`{len(deleted)}` message(s) supprimé(s)",
            extra=f"**Filtre membre** {member.mention}" if member else "",
            color=0xED4245,
        )

        body = f"Deleted `{len(deleted)}` message(s) in {interaction.channel.mention}."
        if old_count:
            body += (f"\n⚠️ `{old_count}` message(s) skipped "
                     "(pinned, or older than 14 days).")
        await ui.send(interaction, ui.ok_card("Purge done", body), ephemeral=True)

    @app_commands.command(name="slowmode", description="Set the slowmode of a channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Seconds (0 = disabled, max 21600).")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.edit(slowmode_delay=seconds)
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Slowmode failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return
        msg = "Slowmode **disabled**." if seconds == 0 else f"Slowmode set to **{seconds}s**."
        await ui.send(interaction, ui.ok_card("Slowmode updated", msg), ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Slowmode", interaction.channel, interaction.user,
            reason=msg.replace("✓ ", ""), color=0x3498DB,
        )

    @app_commands.command(name="lock", description="Lock a channel or thread.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(locked=True)
            else:
                overwrite = channel.overwrites_for(interaction.guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Lock failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return
        await ui.send(interaction, ui.ok_card(
            "🔒 Channel locked", f"{interaction.channel.mention} is read-only until unlocked."
        ), ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Salon verrouillé", interaction.channel, interaction.user,
            color=0xED4245,
        )

    @app_commands.command(name="unlock", description="Unlock a channel or thread.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(locked=False)
            else:
                overwrite = channel.overwrites_for(interaction.guild.default_role)
                overwrite.send_messages = None
                await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        except discord.HTTPException as e:
            await ui.send(interaction, ui.error_card(
                "Unlock failed",
                f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
            ), ephemeral=True)
            return
        await ui.send(interaction, ui.ok_card(
            "🔓 Channel unlocked", f"{interaction.channel.mention} is open for everyone again."
        ), ephemeral=True)
        await loghub.mod_action(
            interaction.guild, "Salon déverrouillé", interaction.channel, interaction.user,
            color=0x57F287,
        )

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
        # Bornes Discord : un "text display" est limité à 4000 caractères.
        title   = title[:200]
        message = message[:3500]

        ping_text = ""
        if ping:
            p = ping.strip()
            if p in ("@here", "@everyone"):
                ping_text = p
            elif p.isdigit():
                role = interaction.guild.get_role(int(p))
                if role:
                    ping_text = role.mention

        # Carte d'annonce construite avec le design system (accent violet info).
        annonce = ui.Card(f"# 📢 {title}", accent=ui.ACCENT_INFO, thumbnail=(
            str(interaction.guild.icon.url) if interaction.guild.icon
            else "https://i.ibb.co/WWbL1v1k/7391989548e4747ad18756fa467b74da.webp"
        ))
        annonce.text(message)
        annonce.divider(spacing=1).footer(
            f"Announcement by {interaction.user.display_name} · <t:{ts}:F>"
        )
        payload = annonce.payload()
        if ping_text:
            payload["components"][0]["components"].insert(0, {"type": 10, "content": ping_text})

        status, resp = await api_send(
            channel.id,
            payload,
            allowed_mentions=MENTIONS_ALL if ping_text else None,
        )
        if status in (200, 201):
            await ui.send(interaction, ui.ok_card(
                "Announcement posted",
                f"{channel.mention} received **{title}**.",
            ), ephemeral=True)
        else:
            await ui.send(interaction, ui.error_card(
                "Announcement failed",
                f"Discord answered `{status}`. Check my permissions in {channel.mention}.",
            ), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))