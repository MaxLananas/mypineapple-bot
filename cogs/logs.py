from __future__ import annotations
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils.api import api_send
from utils.helpers import ts_now
from config import LOG_HUB_CHANNEL_ID

log = logging.getLogger(__name__)

THREAD_NAMES = {
    "messages":   "📝 messages",
    "members":    "👥 members",
    "roles":      "🎭 roles",
    "channels":   "📺 channels",
    "voice":      "🔊 voice",
    "moderation": "🔨 moderation",
    "server":     "⚙️ server",
    "joins":      "🚪 joins",
    "leaves":     "🚪 leaves",
    "avatars":    "🖼️ avatars",
}

_thread_cache:    dict[str, int] = {}
_snipe_cache:     dict[int, dict] = {}
_editsnipe_cache: dict[int, dict] = {}


async def _get_or_create_thread(guild: discord.Guild, key: str) -> discord.Thread | None:
    if key in _thread_cache:
        thread = guild.get_thread(_thread_cache[key])
        if thread:
            return thread

    parent = guild.get_channel(LOG_HUB_CHANNEL_ID)
    if not parent or not isinstance(parent, discord.TextChannel):
        return None

    name = THREAD_NAMES.get(key, key)

    for thread in parent.threads:
        if thread.name == name:
            _thread_cache[key] = thread.id
            return thread

    try:
        async for thread in parent.archived_threads(limit=50):
            if thread.name == name:
                await thread.unarchive()
                _thread_cache[key] = thread.id
                return thread
    except Exception:
        pass

    try:
        thread = await parent.create_thread(
            name=name,
            auto_archive_duration=10080,
            reason="Log thread creation",
        )
        _thread_cache[key] = thread.id
        log.info("Log thread created: %s (%d)", name, thread.id)
        return thread
    except Exception as e:
        log.error("Cannot create log thread %s: %s", name, e)
        return None


async def _log(guild: discord.Guild, key: str, accent: int, content: str) -> None:
    thread = await _get_or_create_thread(guild, key)
    if not thread:
        return
    try:
        await api_send(thread.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": accent,
                    "components": [{"type": 10, "content": content}],
                }
            ],
        })
    except Exception as e:
        log.error("_log(%s): %s", key, e)


class Logs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        ts = ts_now()

        _snipe_cache[message.channel.id] = {
            "author":  str(message.author),
            "avatar":  str(message.author.display_avatar.url),
            "content": message.content[:800] if message.content else "",
            "ts":      ts,
        }

        content_display = message.content[:800] if message.content else "*No text content*"
        await _log(
            message.guild, "messages", 0xED4245,
            f"## 🗑️ Message Deleted\n"
            f"**Author** {message.author.mention} (`{message.author.id}`)\n"
            f"**Channel** {message.channel.mention}\n"
            f"**Content** {content_display}\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        ts = ts_now()

        _editsnipe_cache[before.channel.id] = {
            "author": str(before.author),
            "avatar": str(before.author.display_avatar.url),
            "before": before.content[:400] if before.content else "",
            "after":  after.content[:400] if after.content else "",
            "ts":     ts,
        }

        await _log(
            before.guild, "messages", 0xFEE75C,
            f"## ✏️ Message Edited\n"
            f"**Author** {before.author.mention} (`{before.author.id}`)\n"
            f"**Channel** {before.channel.mention}\n"
            f"**Before** {before.content[:400] or '*empty*'}\n"
            f"**After** {after.content[:400] or '*empty*'}\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ts      = ts_now()
        created = int(member.created_at.timestamp())
        await _log(
            member.guild, "joins", 0x57F287,
            f"## 📥 Member Joined\n"
            f"**User** {member.mention} (`{member.id}`)\n"
            f"**Tag** `{member}`\n"
            f"**Account created** <t:{created}:R>\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        ts    = ts_now()
        roles = [r.name for r in member.roles if r.name != "@everyone"]
        await _log(
            member.guild, "leaves", 0xED4245,
            f"## 📤 Member Left\n"
            f"**User** `{member}` (`{member.id}`)\n"
            f"**Roles** {', '.join(roles) if roles else 'None'}\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        ts = ts_now()

        if before.nick != after.nick:
            await _log(
                before.guild, "members", 0xA8D8EA,
                f"## 📝 Nickname Changed\n"
                f"**User** {after.mention} (`{after.id}`)\n"
                f"**Before** `{before.nick or before.name}`\n"
                f"**After** `{after.nick or after.name}`\n"
                f"**At** <t:{ts}:F>",
            )

        added = [r for r in after.roles if r not in before.roles]
        if added:
            await _log(
                before.guild, "roles", 0x57F287,
                f"## ➕ Role(s) Added\n"
                f"**User** {after.mention} (`{after.id}`)\n"
                f"**Roles** {' '.join(r.mention for r in added)}\n"
                f"**At** <t:{ts}:F>",
            )

        removed = [r for r in before.roles if r not in after.roles]
        if removed:
            await _log(
                before.guild, "roles", 0xED4245,
                f"## ➖ Role(s) Removed\n"
                f"**User** {after.mention} (`{after.id}`)\n"
                f"**Roles** {' '.join(r.mention for r in removed)}\n"
                f"**At** <t:{ts}:F>",
            )

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.display_avatar.url == after.display_avatar.url:
            return
        ts = ts_now()
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member:
                await _log(
                    guild, "avatars", 0xC3B1E1,
                    f"## 🖼️ Avatar Changed\n"
                    f"**User** {member.mention} (`{member.id}`)\n"
                    f"**New avatar** {after.display_avatar.url}\n"
                    f"**At** <t:{ts}:F>",
                )
                break

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        ts = ts_now()
        await _log(
            channel.guild, "channels", 0x57F287,
            f"## 📺 Channel Created\n"
            f"**Name** {channel.mention} (`{channel.id}`)\n"
            f"**Type** `{channel.type}`\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        ts = ts_now()
        await _log(
            channel.guild, "channels", 0xED4245,
            f"## 📺 Channel Deleted\n"
            f"**Name** `{channel.name}` (`{channel.id}`)\n"
            f"**Type** `{channel.type}`\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.name == after.name:
            return
        ts = ts_now()
        await _log(
            before.guild, "channels", 0xFEE75C,
            f"## 📺 Channel Renamed\n"
            f"**Before** `{before.name}`\n"
            f"**After** `{after.name}`\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        ts = ts_now()
        if before.channel is None and after.channel is not None:
            await _log(member.guild, "voice", 0x57F287,
                f"## 🔊 Joined Voice\n**User** {member.mention} (`{member.id}`)\n**Channel** {after.channel.mention}\n**At** <t:{ts}:F>")
        elif before.channel is not None and after.channel is None:
            await _log(member.guild, "voice", 0xED4245,
                f"## 🔇 Left Voice\n**User** {member.mention} (`{member.id}`)\n**Channel** {before.channel.mention}\n**At** <t:{ts}:F>")
        elif before.channel != after.channel and before.channel and after.channel:
            await _log(member.guild, "voice", 0xFEE75C,
                f"## 🔀 Switched Voice Channel\n**User** {member.mention} (`{member.id}`)\n**From** {before.channel.mention}\n**To** {after.channel.mention}\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        ts = ts_now()
        await _log(role.guild, "roles", 0x57F287,
            f"## 🎭 Role Created\n**Name** {role.mention} (`{role.id}`)\n**Colour** `{role.colour}`\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        ts = ts_now()
        await _log(role.guild, "roles", 0xED4245,
            f"## 🎭 Role Deleted\n**Name** `{role.name}` (`{role.id}`)\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        ts = ts_now()
        await _log(guild, "moderation", 0xED4245,
            f"## 🔨 Member Banned\n**User** `{user}` (`{user.id}`)\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        ts = ts_now()
        await _log(guild, "moderation", 0x57F287,
            f"## ✅ Member Unbanned\n**User** `{user}` (`{user.id}`)\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        ts      = ts_now()
        changes = []
        if before.name != after.name:
            changes.append(f"**Name** `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Icon** changed")
        if before.premium_tier != after.premium_tier:
            changes.append(f"**Boost level** `{before.premium_tier}` → `{after.premium_tier}`")
        if not changes:
            return
        await _log(before, "server", 0x9B8EC4,
            f"## ⚙️ Server Updated\n" + "\n".join(changes) + f"\n**At** <t:{ts}:F>")

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list, after: list):
        ts      = ts_now()
        added   = [e for e in after  if e not in before]
        removed = [e for e in before if e not in after]
        if added:
            await _log(guild, "server", 0x57F287,
                f"## 😄 Emoji(s) Added\n{' '.join(str(e) for e in added)}\n**At** <t:{ts}:F>")
        if removed:
            await _log(guild, "server", 0xED4245,
                f"## 😢 Emoji(s) Removed\n{', '.join(f'`{e.name}`' for e in removed)}\n**At** <t:{ts}:F>")


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))