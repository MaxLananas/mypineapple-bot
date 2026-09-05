from __future__ import annotations
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils.api import api_send, media_gallery, get_session
from utils.helpers import ts_now
from config import LOG_HUB_CHANNEL_ID, SUPPORT_ROLE_ID

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
# Cache des profils (banner / bio) pour détecter les changements.
_user_meta_cache: dict[int, dict] = {}
# Anti-spam des statuts : ne log un changement de statut que si suffisamment de
# temps s'est écoulé depuis le dernier log (évite le flood des "bump bots").
_presence_cooldown: dict[int, float] = {}
PRESENCE_LOG_COOLDOWN = 600.0  # 10 minutes min entre 2 logs de statut par user


def _banner_url(user_id: int, banner_hash: str) -> str:
    ext = "gif" if banner_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/banners/{user_id}/{banner_hash}.{ext}?size=1024"


async def _fetch_profile(user_id: int) -> dict:
    """Récupère bio + banner + accent via l'API REST (non exposés par discord.py)."""
    try:
        session = get_session()
    except RuntimeError:
        return {}
    try:
        async with session.get(f"https://discord.com/api/v10/users/{user_id}") as r:
            if r.status != 200:
                return {}
            return await r.json()
    except Exception as e:
        log.warning("_fetch_profile(%s): %s", user_id, e)
        return {}


def _thumbnail(url: str) -> dict:
    """Accessoire média (type 11) — affiche l'image en vignette."""
    return {"type": 11, "media": {"url": url}}


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


async def _log(
    guild: discord.Guild,
    key: str,
    accent: int,
    content: str,
    *,
    gallery: list[str] | list[tuple[str, str | None]] | None = None,
    thumbnail: str | None = None,
) -> None:
    thread = await _get_or_create_thread(guild, key)
    if not thread:
        return

    # En-tête avec vignette (avatar / image).
    header = {"type": 10, "content": content}
    if thumbnail:
        header = {
            "type": 9,
            "components": [{"type": 10, "content": content}],
            "accessory": _thumbnail(thumbnail),
        }

    inner = [header]
    if gallery:
        inner.append(media_gallery(gallery))

    try:
        await api_send(thread.id, {
            "flags": 32768,
            "components": [
                {"type": 17, "accent_color": accent, "components": inner}
            ],
        })
    except Exception as e:
        log.error("_log(%s): %s", key, e)


def _attachments_media(message: discord.Message) -> list[str]:
    """URLs des pièces jointes affichables en galerie (images/vidéos)."""
    return [
        a.url
        for a in message.attachments
        if a.content_type and a.content_type.startswith(("image/", "video/"))
    ]


class Logs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Messages ────────────────────────────────────────────────────────────

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
        media = _attachments_media(message)

        await _log(
            message.guild, "messages", 0xED4245,
            f"## 🗑️ Message Deleted\n"
            f"**Author** {message.author.mention} (`{message.author.id}`)\n"
            f"**Channel** {message.channel.mention}\n"
            f"**Content** {content_display}\n"
            f"**At** <t:{ts}:F>",
            thumbnail=str(message.author.display_avatar.url),
            gallery=media or None,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        first = messages[0]
        guild = getattr(first, "guild", None)
        if not guild:
            return
        ts = ts_now()

        humans = [m for m in messages if not m.author.bot]
        lines = []
        for m in humans[:15]:
            text = m.content[:120].replace("\n", " ") if m.content else "*[no text]*"
            lines.append(f"• {m.author.mention}: {text}")
        extra = f"\n… and {len(humans) - 15} more" if len(humans) > 15 else ""

        await _log(
            guild, "messages", 0xED4245,
            f"## 🧹 Bulk Delete ({len(messages)} messages)\n"
            f"**Channel** {first.channel.mention}\n"
            f"**At** <t:{ts}:F>\n\n" + "\n".join(lines) + extra,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content and before.attachments == after.attachments:
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
            thumbnail=str(before.author.display_avatar.url),
        )

    # ── Membres ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ts      = ts_now()
        created = int(member.created_at.timestamp())
        age     = ts - created
        new_acc = age < 86400  # account created less than 24h ago
        # Ping staff so a moderator can keep an eye on fresh accounts.
        staff_ping = f" <@&{SUPPORT_ROLE_ID}>" if new_acc else ""
        await _log(
            member.guild, "joins", 0xED4245 if new_acc else 0x57F287,
            f"## {'⚠️' if new_acc else '📥'} Member Joined\n"
            f"**User** {member.mention} (`{member.id}`)\n"
            f"**Tag** `{member}`\n"
            f"**Account created** <t:{created}:R>\n"
            + ("**⚠️ NEW ACCOUNT (< 24h)** — possible alt / raid." + staff_ping + "\n" if new_acc else "")
            + f"**At** <t:{ts}:F>",
            thumbnail=str(member.display_avatar.url),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        ts = ts_now()
        roles = [r.name for r in member.roles if r.name != "@everyone"]
        await _log(
            member.guild, "leaves", 0xED4245,
            f"## 📤 Member Left\n"
            f"**User** `{member}` (`{member.id}`)\n"
            f"**Roles** {', '.join(roles) if roles else 'None'}\n"
            f"**At** <t:{ts}:F>",
            thumbnail=str(member.display_avatar.url),
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
                thumbnail=str(after.display_avatar.url),
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

    # ── Utilisateur global (bio / avatar) ───────────────────────────────────

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        ts = ts_now()

        # Avatar : afficher l'image, pas un lien.
        if before.display_avatar.url != after.display_avatar.url:
            for guild in self.bot.guilds:
                member = guild.get_member(after.id)
                if member:
                    await _log(
                        guild, "avatars", 0xC3B1E1,
                        f"## 🖼️ Avatar Changed\n"
                        f"**User** {member.mention} (`{member.id}`)\n"
                        f"**At** <t:{ts}:F>",
                        thumbnail=str(after.display_avatar.url),
                        gallery=[str(after.display_avatar.with_size(1024).url)],
                    )
                    break

        # Bio / bannière (via REST, car non fournis par l'événement gateway).
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if not member:
                continue
            profile = await _fetch_profile(after.id)
            if not profile:
                break
            prev = _user_meta_cache.get(after.id, {})
            banner = profile.get("banner")
            bio = profile.get("bio")
            accent = profile.get("accent_color")

            if banner and banner != prev.get("banner"):
                await _log(
                    guild, "avatars", 0x57F287,
                    f"## 🖼️ Banner Changed\n"
                    f"**User** {member.mention} (`{member.id}`)\n"
                    f"**At** <t:{ts}:F>",
                    gallery=[_banner_url(after.id, banner)],
                )
            elif banner is None and prev.get("banner"):
                await _log(
                    guild, "avatars", 0xED4245,
                    f"## 🖼️ Banner Removed\n"
                    f"**User** {member.mention} (`{member.id}`)\n"
                    f"**At** <t:{ts}:F>",
                )

            if bio != prev.get("bio"):
                old = prev.get("bio") or "*none*"
                new = bio or "*none*"
                await _log(
                    guild, "members", 0xF7CAC9,
                    f"## 📝 Bio Changed\n"
                    f"**User** {member.mention} (`{member.id}`)\n"
                    f"**Before** {old[:300]}\n"
                    f"**After** {new[:300]}\n"
                    f"**At** <t:{ts}:F>",
                )

            _user_meta_cache[after.id] = {"banner": banner, "bio": bio, "accent": accent}
            break

    # ── Statuts / activités (anti-spam) ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        # Ignore les bots (bump bots, etc.) qui font tourner leur statut en boucle.
        if after.bot:
            return

        now = time.time()
        if now - _presence_cooldown.get(after.id, 0) < PRESENCE_LOG_COOLDOWN:
            return

        before_custom = next(
            (a.state for a in before.activities if a.type == discord.ActivityType.custom),
            None,
        )
        after_custom = next(
            (a.state for a in after.activities if a.type == discord.ActivityType.custom),
            None,
        )

        # Ne log que les NOUVEAUX statuts custom (pas les "cleared" = bruit).
        if after_custom and after_custom != before_custom:
            _presence_cooldown[after.id] = now
            await _log(
                after.guild, "members", 0xF7CAC9,
                f"## 🏷️ Custom Status Set\n"
                f"**User** {after.mention} (`{after.id}`)\n"
                f"**Status** {after_custom[:200]}\n"
                f"**At** <t:{ts_now()}:F>",
            )
            return

        # Activité (jeu / stream / écoute) — throttlé pareil.
        before_act = next(
            (a.name for a in before.activities if a.type != discord.ActivityType.custom),
            None,
        )
        after_act = next(
            (a.name for a in after.activities if a.type != discord.ActivityType.custom),
            None,
        )
        if after_act and after_act != before_act:
            _presence_cooldown[after.id] = now
            await _log(
                after.guild, "members", 0xA8D8EA,
                f"## 🎮 Activity Started\n"
                f"**User** {after.mention} (`{after.id}`)\n"
                f"**Playing** {after_act[:200]}\n"
                f"**At** <t:{ts_now()}:F>",
            )

    # ── Invitations ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        ts = ts_now()
        await _log(
            invite.guild, "server", 0x57F287,
            f"## 🔗 Invite Created\n"
            f"**Code** `{invite.code}`\n"
            f"**Channel** {invite.channel.mention if invite.channel else '?'}\n"
            f"**By** {invite.inviter.mention if invite.inviter else '?'}\n"
            f"**Max uses** `{invite.max_uses if invite.max_uses else '∞'}`\n"
            f"**At** <t:{ts}:F>",
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        ts = ts_now()
        await _log(
            invite.guild, "server", 0xED4245,
            f"## 🔗 Invite Deleted\n"
            f"**Code** `{invite.code}`\n"
            f"**Channel** {invite.channel.mention if invite.channel else '?'}\n"
            f"**At** <t:{ts}:F>",
        )

    # ── Webhooks ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        ts = ts_now()
        try:
            webhooks = await channel.webhooks()
        except discord.Forbidden:
            webhooks = []
        names = ", ".join(f"`{w.name}`" for w in webhooks) or "none"
        await _log(
            channel.guild, "server", 0x9B8EC4,
            f"## 🪝 Webhooks Updated\n"
            f"**Channel** {channel.mention}\n"
            f"**Webhooks** {names}\n"
            f"**At** <t:{ts}:F>",
        )

    # ── Canaux ──────────────────────────────────────────────────────────────

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
        ts = ts_now()
        if before.name != after.name:
            await _log(
                before.guild, "channels", 0xFEE75C,
                f"## 📺 Channel Renamed\n"
                f"**Before** `{before.name}`\n"
                f"**After** `{after.name}`\n"
                f"**At** <t:{ts}:F>",
            )

        # Changement de permissions (overwrites).
        if isinstance(before, discord.abc.GuildChannel) and isinstance(after, discord.abc.GuildChannel):
            b_over = {str(k.id) if hasattr(k, "id") else str(k): v for k, v in before.overwrites.items()}
            a_over = {str(k.id) if hasattr(k, "id") else str(k): v for k, v in after.overwrites.items()}
            if b_over != a_over:
                # Décrit sommairement ce qui a changé.
                changed = []
                for key in set(b_over) | set(a_over):
                    ob, oa = b_over.get(key), a_over.get(key)
                    if ob != oa:
                        target = after.guild.get_role(int(key)) or after.guild.get_member(int(key))
                        name = target.name if target else key
                        changed.append(f"`{name}`")
                await _log(
                    before.guild, "channels", 0x9B8EC4,
                    f"## 🛡️ Channel Permissions Changed\n"
                    f"**Channel** {after.mention}\n"
                    f"**Targets** {', '.join(changed) or '?'}\n"
                    f"**At** <t:{ts}:F>",
                )

    # ── Voix ────────────────────────────────────────────────────────────────

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

    # ── Rôles / Serveur ─────────────────────────────────────────────────────

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
