"""Logs « Big Brother » — surveillance complète du serveur.

Chaque type d'événement part dans son salon dédié (catégorie privée créée par
``/logssetup``, visible uniquement par le rôle ``LOG_ACCESS_ROLE_ID``) :

| Salon | Contenu |
|-------|---------|
| 📥 messages | tous les messages envoyés (texte, pièces jointes, liens, réponses…) |
| ✏️ éditions | messages modifiés (avant / après) |
| 🗑️ suppressions | messages supprimés (+ cache `/snipe`) |
| 👥 membres | arrivées, départs, pseudos |
| 🖼️ profils | avatar, bannière, bio, nom (avant **et** après) |
| 🟢 statuts | statuts en ligne / personnalisés / activités |
| 🚪 invitations | qui invite qui, codes, sources |
| ⌨️ commandes | chaque slash-command utilisée (+ erreurs) |
| 🔨 modération | bans, kicks, timeouts, avertissements |
| 🎭 rôles | création, suppression, attribution |
| 📺 salons | création, suppression, renommage, permissions |
| 🔊 vocal | entrées, sorties, déplacements, mute, stream |
| ⚙️ serveur | infos serveur, émojis, boosts, webhooks |
| 🧵 fils | fils de discussion |
| 🚨 sécurité | nouveaux comptes, raids, anti-spam |
| 🕵️ audit | journal d'audit Discord (qui a fait quoi) |
| 📊 statistiques | rapports périodiques + `/logstats` |
| 🤖 bot | démarrages, erreurs, synchronisation |

Sans ``/logssetup``, tout retombe automatiquement sur des threads dans
``LOG_HUB_CHANNEL_ID`` : aucun événement n'est perdu.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import utils.db as db
import utils.loghub as loghub
from utils.api import get_session
from utils.helpers import ts_now
from config import LOG_ACCESS_ROLE_ID, SUPPORT_ROLE_ID

log = logging.getLogger(__name__)

# ── Caches ───────────────────────────────────────────────────────────────────
_snipe_cache:     dict[int, dict] = {}
_editsnipe_cache: dict[int, dict] = {}
# (guild_id, user_id) -> timestamp d'arrivée en vocal
_voice_sessions:  dict[tuple[int, int], float] = {}
# Anti-spam des statuts (évite le flood des bump bots).
_presence_cooldown: dict[int, float] = {}
PRESENCE_LOG_COOLDOWN = 300.0
_PROFILE_CACHE_MAX = 3000

# Permissions « dangereuses » mises en évidence dans les logs de rôles.
_DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "mention_everyone",
    "manage_messages", "moderate_members", "manage_expressions",
)


def _esc(text: str, limit: int = 1500) -> str:
    """Nettoie/borne un texte utilisateur (évite les mentions et les 400)."""
    if not text:
        return ""
    text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    return text[:limit] + ("… *(tronqué)*" if len(text) > limit else "")


def _stamp(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    return f"<t:{int(dt.timestamp())}:F>"


def _size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


# ── Profils persistés (pour connaître l'« avant » même après un restart) ─────

def _profiles() -> dict:
    cfg = db.config()
    prof = cfg.get("user_profiles")
    if not isinstance(prof, dict):
        prof = cfg["user_profiles"] = {}
    return prof


def _save_profile(user_id: int, data: dict) -> None:
    prof = _profiles()
    prof[str(user_id)] = data
    if len(prof) > _PROFILE_CACHE_MAX:
        for old in list(prof)[:_PROFILE_CACHE_MAX // 2]:
            prof.pop(old, None)
    db.save_config(db.config())


def _get_profile(user_id: int) -> dict:
    rec = _profiles().get(str(user_id), {})
    return rec if isinstance(rec, dict) else {}


def _banner_url(user_id: int, key: str | None) -> str | None:
    if not key:
        return None
    ext = "gif" if key.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/banners/{user_id}/{key}.{ext}?size=1024"


async def _fetch_profile(user_id: int, guild_id: int | None = None) -> dict:
    """Bannière + accent (et bio quand Discord l'expose) via l'API REST.

    L'événement gateway ``on_user_update`` ne transporte que le pseudo, l'avatar
    et le nom global : bannière / accent / bio doivent être récupérés à part.
    On tente ``/users/{id}`` puis, en complément, l'objet membre du serveur qui
    expose parfois le champ ``bio``.
    """
    try:
        session = get_session()
    except RuntimeError:
        return {}

    data: dict = {}
    try:
        async with session.get(f"https://discord.com/api/v10/users/{user_id}") as r:
            if r.status == 200:
                data = await r.json()
    except Exception as e:
        log.warning("_fetch_profile(%s): %s", user_id, e)
        return {}

    if guild_id and not data.get("bio"):
        try:
            async with session.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
            ) as r:
                if r.status == 200:
                    member_data = await r.json()
                    for field in ("bio", "banner", "accent_color"):
                        if member_data.get(field) and not data.get(field):
                            data[field] = member_data[field]
        except Exception as e:
            log.debug("_fetch_profile member(%s): %s", user_id, e)
    return data


# ── Vérification des accès aux commandes ─────────────────────────────────────

def _has_log_access(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.administrator:
        return True
    return any(r.id == LOG_ACCESS_ROLE_ID for r in user.roles)


def log_access_only():
    """Check : rôle de logs (ou administrateur)."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_log_access(interaction):
            return True
        raise app_commands.CheckFailure(
            "This command is reserved for the log access role."
        )
    return app_commands.check(predicate)


# ── Cog ──────────────────────────────────────────────────────────────────────

class Logs(commands.Cog):
    """Surveillance complète : messages, profils, vocal, modération, audit…"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.digest_loop.start()

    def cog_unload(self):
        self.digest_loop.cancel()

    # ── Messages ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or loghub.is_log_channel(message.channel):
            return

        loghub.bump(
            message.guild.id, "messages",
            user_id=message.author.id, channel_id=message.channel.id,
        )
        if not loghub.is_enabled(message.guild.id, "messages"):
            return

        author = message.author
        bot_tag = " 🤖" if author.bot else ""
        lines = [
            "## 📥 Message envoyé",
            f"**Auteur** {author.mention} (`{author}` · `{author.id}`){bot_tag}",
            f"**Salon** {message.channel.mention} · [ouvrir]({message.jump_url})",
            f"**ID** `{message.id}`",
        ]

        if message.reference and message.reference.resolved is not None:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                lines.append(
                    f"**Réponse à** {ref.author.mention} — [message]({ref.jump_url})"
                )
        if message.content:
            lines.append(f"\n**Contenu**\n{_esc(message.content)}")
        elif not message.attachments and not message.stickers:
            lines.append("\n*— message sans texte —*")

        gallery: list = []
        if message.attachments:
            attach_lines = []
            for att in message.attachments[:10]:
                attach_lines.append(f"• [`{att.filename}`]({att.url}) — {_size(att.size)}")
                if (att.content_type or "").startswith("image/"):
                    gallery.append((att.url, att.filename[:100]))
            lines.append("**Pièces jointes**\n" + "\n".join(attach_lines))
        if message.stickers:
            lines.append("**Stickers** " + " ".join(s.name for s in message.stickers))
        if message.embeds:
            lines.append(f"**Embeds** `{len(message.embeds)}`")

        await loghub.log(
            message.guild, "messages", "\n".join(lines),
            thumbnail=str(author.display_avatar.url),
            gallery=gallery or None,
            queued=True,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or loghub.is_log_channel(before.channel):
            return
        if before.content == after.content and before.attachments == after.attachments:
            return

        loghub.bump(before.guild.id, "edits", user_id=before.author.id,
                    channel_id=before.channel.id)
        _editsnipe_cache[before.channel.id] = {
            "author": str(before.author),
            "avatar": str(before.author.display_avatar.url),
            "before": before.content[:400] if before.content else "",
            "after":  after.content[:400] if after.content else "",
            "ts":     ts_now(),
        }

        await loghub.log(
            before.guild, "edits",
            "## ✏️ Message modifié\n"
            f"**Auteur** {before.author.mention} (`{before.author}` · `{before.author.id}`)\n"
            f"**Salon** {before.channel.mention} · [ouvrir]({after.jump_url})\n"
            f"**ID** `{before.id}`\n\n"
            f"**Avant**\n{_esc(before.content) or '*vide*'}\n\n"
            f"**Après**\n{_esc(after.content) or '*vide*'}",
            thumbnail=str(before.author.display_avatar.url),
            queued=True,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or loghub.is_log_channel(message.channel):
            return

        loghub.bump(message.guild.id, "deletes", user_id=message.author.id,
                    channel_id=message.channel.id)
        _snipe_cache[message.channel.id] = {
            "author":  str(message.author),
            "avatar":  str(message.author.display_avatar.url),
            "content": message.content[:800] if message.content else "",
            "ts":      ts_now(),
        }

        gallery = [
            (a.url, a.filename[:100])
            for a in message.attachments
            if (a.content_type or "").startswith(("image/", "video/"))
        ][:10]

        attach = ""
        if message.attachments:
            attach = "\n**Pièces jointes**\n" + "\n".join(
                f"• [`{a.filename}`]({a.url}) — {_size(a.size)}" for a in message.attachments[:10]
            )

        await loghub.log(
            message.guild, "deletes",
            "## 🗑️ Message supprimé\n"
            f"**Auteur** {message.author.mention} (`{message.author}` · `{message.author.id}`)\n"
            f"**Salon** {message.channel.mention}\n"
            f"**Envoyé** {_stamp(message.created_at)} · **ID** `{message.id}`\n\n"
            f"**Contenu**\n{_esc(message.content) or '*aucun texte*'}"
            f"{attach}",
            thumbnail=str(message.author.display_avatar.url),
            gallery=gallery or None,
            queued=True,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        first = messages[0]
        guild = getattr(first, "guild", None)
        if guild is None or loghub.is_log_channel(first.channel):
            return

        humans = [m for m in messages if not m.author.bot]
        lines = []
        for m in humans[:20]:
            text = _esc(m.content, 120).replace("\n", " ") or "*[pas de texte]*"
            lines.append(f"• {m.author.mention} (`{m.author.id}`) — {text}")
        extra = f"\n… et **{len(humans) - 20}** autre(s)" if len(humans) > 20 else ""

        loghub.bump(guild.id, "deletes", amount=len(messages), channel_id=first.channel.id)

        await loghub.log(
            guild, "deletes",
            f"## 🧹 Suppression en masse — {len(messages)} messages\n"
            f"**Salon** {first.channel.mention}\n"
            f"**At** {_stamp(datetime.now(timezone.utc))}\n\n"
            + "\n".join(lines) + extra,
        )

    # ── Membres ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        loghub.bump(guild.id, "joins", user_id=member.id)

        created = member.created_at
        age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        new_acc = age_h < 24

        await loghub.log(
            guild, "members",
            "## 📥 Arrivée\n"
            f"**Membre** {member.mention} (`{member}` · `{member.id}`)\n"
            f"**Compte créé** {_stamp(created)} (<t:{int(created.timestamp())}:R>)\n"
            f"**Comptes** `{guild.member_count}` membres\n"
            f"**Rôles** "
            + (", ".join(r.mention for r in member.roles if r.name != "@everyone") or "*aucun*")
            + ("\n\n⚠️ **Compte de moins de 24 h** — possible alt / raid." if new_acc else ""),
            thumbnail=str(member.display_avatar.url),
        )

        if new_acc:
            await loghub.log(
                guild, "security",
                "## 🚨 Nouveau compte détecté\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**Créé il y a** `{age_h:.1f} h` · {_stamp(created)}\n"
                f"**Pseudo** `{member}`\n"
                f"**Salon d'arrivée** {guild.system_channel.mention if guild.system_channel else '?'}\n\n"
                f"<@&{SUPPORT_ROLE_ID}> — vérification recommandée.",
                thumbnail=str(member.display_avatar.url),
                mentions={"parse": [], "roles": [SUPPORT_ROLE_ID], "users": [], "replied_user": False},
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        loghub.bump(guild.id, "leaves", user_id=member.id)

        stayed = ""
        if member.joined_at:
            delta = datetime.now(timezone.utc) - member.joined_at
            days, rem = divmod(int(delta.total_seconds()), 86400)
            hours, _ = divmod(rem, 3600)
            stayed = f"\n**Resté** `{days} j {hours} h` (<t:{int(member.joined_at.timestamp())}:R>)"

        roles = [r.mention for r in member.roles if r.name != "@everyone"]

        await loghub.log(
            guild, "members",
            "## 📤 Départ\n"
            f"**Membre** `{member}` (`{member.id}`)\n"
            f"**Pseudo affiché** `{member.display_name}`"
            f"{stayed}\n"
            f"**Rôles au départ** {', '.join(roles) or '*aucun*'}\n"
            f"**Membres restants** `{guild.member_count}`",
            thumbnail=str(member.display_avatar.url),
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = before.guild

        if before.nick != after.nick:
            await loghub.log(
                guild, "members",
                "## 📝 Pseudo modifié\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Avant** `{before.nick or before.name}`\n"
                f"**Après** `{after.nick or after.name}`",
                thumbnail=str(after.display_avatar.url),
            )

        added   = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added:
            await loghub.log(
                guild, "roles",
                "## ➕ Rôle(s) ajouté(s)\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Rôles** {' '.join(r.mention for r in added)}",
                thumbnail=str(after.display_avatar.url),
            )
        if removed:
            await loghub.log(
                guild, "roles",
                "## ➖ Rôle(s) retiré(s)\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Rôles** {' '.join(r.mention for r in removed)}",
                thumbnail=str(after.display_avatar.url),
            )

        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until and after.timed_out_until > datetime.now(timezone.utc):
                await loghub.log(
                    guild, "moderation",
                    "## 🔇 Timeout appliqué\n"
                    f"**Membre** {after.mention} (`{after.id}`)\n"
                    f"**Jusqu'à** {_stamp(after.timed_out_until)}",
                    thumbnail=str(after.display_avatar.url),
                )
            else:
                await loghub.log(
                    guild, "moderation",
                    "## 🔊 Timeout retiré\n"
                    f"**Membre** {after.mention} (`{after.id}`)",
                    thumbnail=str(after.display_avatar.url),
                )

    # ── Profil global (avatar, bannière, bio, nom) ──────────────────────────

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        now = datetime.now(timezone.utc)

        # Un seul serveur de destination : celui où l'utilisateur est membre.
        guild = member = None
        for g in self.bot.guilds:
            m = g.get_member(after.id)
            if m is not None:
                guild, member = g, m
                break
        if guild is None:
            return

        # Nom d'utilisateur / nom global
        if before.name != after.name or before.global_name != after.global_name:
            await loghub.log(
                guild, "profiles",
                "## 🪪 Nom modifié\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**Nom d'utilisateur** `{before.name}` → `{after.name}`\n"
                f"**Nom global** `{before.global_name or '—'}` → `{after.global_name or '—'}`",
                thumbnail=str(after.display_avatar.url),
            )

        # Avatar : ancien ET nouveau
        if before.display_avatar.url != after.display_avatar.url:
            await loghub.log(
                guild, "profiles",
                "## 🖼️ Avatar modifié\n"
                f"**Membre** {member.mention} (`{member.id}`)",
                gallery=[
                    (str(before.display_avatar.replace(size=1024, static_format="png").url), "Avant"),
                    (str(after.display_avatar.replace(size=1024, static_format="png").url), "Après"),
                ],
            )

        prev = _get_profile(after.id)
        # Premier passage : on ne connaît pas l'état précédent (cache vide après
        # un restart). On se contente de mémoriser, sinon chaque démarrage
        # produirait un faux « Bio/Bannière modifiée ».
        first_seen = not prev

        # Bannière / bio / accent : récupérés via REST (absents du gateway).
        profile    = await _fetch_profile(after.id, guild.id)
        banner     = profile.get("banner")
        bio        = profile.get("bio")
        accent     = profile.get("accent_color")
        old_banner = _banner_url(after.id, prev.get("banner"))
        new_banner = _banner_url(after.id, banner)

        if not first_seen and new_banner and banner != prev.get("banner"):
            gallery = [(new_banner, "Après")]
            if old_banner:
                gallery.insert(0, (old_banner, "Avant"))
            await loghub.log(
                guild, "profiles",
                "## 🏳️ Bannière modifiée\n"
                f"**Membre** {member.mention} (`{member.id}`)",
                gallery=gallery,
            )
        elif not first_seen and old_banner and not new_banner:
            await loghub.log(
                guild, "profiles",
                "## 🏳️ Bannière retirée\n"
                f"**Membre** {member.mention} (`{member.id}`)",
                gallery=[(old_banner, "Avant")],
            )

        # Bio / « à propos »
        if not first_seen and bio != prev.get("bio"):
            await loghub.log(
                guild, "profiles",
                "## 📝 Bio modifiée\n"
                f"**Membre** {member.mention} (`{member.id}`)\n\n"
                f"**Avant**\n{_esc(prev.get('bio') or '', 300) or '*vide*'}\n\n"
                f"**Après**\n{_esc(bio or '', 300) or '*vide*'}",
                thumbnail=str(after.display_avatar.url),
            )

        if not first_seen and accent is not None and accent != prev.get("accent"):
            await loghub.log(
                guild, "profiles",
                "## 🎨 Couleur d'accent modifiée\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**Couleur** `#{accent:06x}`",
            )

        # Mémorise l'état courant (bannière/bio/accent/nom) pour l'« avant » suivant.
        _save_profile(after.id, {
            "avatar":      after.avatar.key if after.avatar else None,
            "display":     after.display_avatar.key if after.display_avatar else None,
            "banner":      banner,
            "bio":         bio,
            "accent":      accent,
            "username":    after.name,
            "global_name": after.global_name,
            "at":          now.isoformat(),
        })

    # ── Statuts / activités ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        now = datetime.now(timezone.utc).timestamp()
        if now - _presence_cooldown.get(after.id, 0) < PRESENCE_LOG_COOLDOWN:
            return
        if len(_presence_cooldown) > 5000:
            for k in [k for k, v in _presence_cooldown.items()
                      if now - v > PRESENCE_LOG_COOLDOWN * 4]:
                _presence_cooldown.pop(k, None)

        status_icon = {
            discord.Status.online:  "🟢",
            discord.Status.idle:    "🌙",
            discord.Status.dnd:     "⛔",
            discord.Status.offline: "⚫",
        }

        if before.status != after.status:
            _presence_cooldown[after.id] = now
            await loghub.log(
                after.guild, "status",
                "## 🔄 Statut modifié\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Avant** {status_icon.get(before.status, '?')} `{before.status}`\n"
                f"**Après** {status_icon.get(after.status, '?')} `{after.status}`",
                thumbnail=str(after.display_avatar.url),
            )
            return

        before_custom = next(
            (a.state for a in before.activities if a.type == discord.ActivityType.custom), None)
        after_custom = next(
            (a.state for a in after.activities if a.type == discord.ActivityType.custom), None)

        if after_custom and after_custom != before_custom:
            _presence_cooldown[after.id] = now
            await loghub.log(
                after.guild, "status",
                "## 💬 Statut personnalisé\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Avant** {_esc(before_custom or '—', 200)}\n"
                f"**Après** {_esc(after_custom, 200)}",
                thumbnail=str(after.display_avatar.url),
            )
            return

        def activity_of(activities):
            for a in activities:
                if a.type == discord.ActivityType.playing:
                    return f"🎮 Joue à **{a.name}**"
                if a.type == discord.ActivityType.streaming:
                    return f"🔴 En stream sur **{a.name}**"
                if a.type == discord.ActivityType.listening:
                    return f"🎧 Écoute **{a.name}**"
                if a.type == discord.ActivityType.watching:
                    return f"📺 Regarde **{a.name}**"
                if a.type == discord.ActivityType.competing:
                    return f"🏆 Compétition **{a.name}**"
            return None

        before_act = activity_of(before.activities)
        after_act  = activity_of(after.activities)
        if after_act and after_act != before_act:
            _presence_cooldown[after.id] = now
            await loghub.log(
                after.guild, "status",
                "## 🎮 Activité\n"
                f"**Membre** {after.mention} (`{after.id}`)\n"
                f"**Avant** {before_act or '*aucune*'}\n"
                f"**Après** {after_act}",
                thumbnail=str(after.display_avatar.url),
            )

    # ── Vocal ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member,
        before: discord.VoiceState, after: discord.VoiceState,
    ):
        if member.bot:
            return
        guild = member.guild
        key = (guild.id, member.id)

        if before.channel is None and after.channel is not None:
            _voice_sessions[key] = datetime.now(timezone.utc).timestamp()
            await loghub.log(
                guild, "voice",
                "## 🔊 Entrée en vocal\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**Salon** {after.channel.mention}",
                thumbnail=str(member.display_avatar.url),
            )
        elif before.channel is not None and after.channel is None:
            duration = ""
            start = _voice_sessions.pop(key, None)
            if start:
                secs = int(datetime.now(timezone.utc).timestamp() - start)
                h, rem = divmod(secs, 3600)
                m, s = divmod(rem, 60)
                duration = f"\n**Durée** `{h} h {m} min {s} s`"
                loghub.bump(guild.id, "voice_seconds", secs, user_id=member.id)
            await loghub.log(
                guild, "voice",
                "## 🔇 Sortie de vocal\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**Salon** {before.channel.mention}{duration}",
                thumbnail=str(member.display_avatar.url),
            )
        elif before.channel != after.channel and before.channel and after.channel:
            await loghub.log(
                guild, "voice",
                "## 🔀 Changement de vocal\n"
                f"**Membre** {member.mention} (`{member.id}`)\n"
                f"**De** {before.channel.mention}\n"
                f"**Vers** {after.channel.mention}",
                thumbnail=str(member.display_avatar.url),
            )

        changes = []
        if before.self_mute != after.self_mute:
            changes.append("🎙️ **Micro coupé**" if after.self_mute else "🎙️ **Micro réactivé**")
        if before.self_deaf != after.self_deaf:
            changes.append("🎧 **Casque coupé**" if after.self_deaf else "🎧 **Casque réactivé**")
        if before.mute != after.mute:
            changes.append("🔇 **Mute serveur**" if after.mute else "🔊 **Démute serveur**")
        if before.deaf != after.deaf:
            changes.append("🔕 **Sourdine serveur**" if after.deaf else "🔔 **Fin de sourdine**")
        if before.self_stream != after.self_stream:
            changes.append("📺 **Stream démarré**" if after.self_stream else "📺 **Stream arrêté**")
        if before.self_video != after.self_video:
            changes.append("📷 **Caméra activée**" if after.self_video else "📷 **Caméra coupée**")
        if changes:
            await loghub.log(
                guild, "voice",
                f"## 🎛️ État vocal — {member.mention}\n" + "\n".join(changes)
                + f"\n**Salon** {(after.channel or before.channel).mention if (after.channel or before.channel) else '?'}",
                thumbnail=str(member.display_avatar.url),
            )

    # ── Salons ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await loghub.log(
            channel.guild, "channels",
            "## 📺 Salon créé\n"
            f"**Nom** {channel.mention} (`{channel.name}`)\n"
            f"**Type** `{channel.type}` · **ID** `{channel.id}`"
            + (f"\n**Catégorie** `{channel.category.name}`" if getattr(channel, "category", None) else ""),
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await loghub.log(
            channel.guild, "channels",
            "## 📺 Salon supprimé\n"
            f"**Nom** `{channel.name}` · **Type** `{channel.type}` · **ID** `{channel.id}`",
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel,
    ):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** `{before.name}` → `{after.name}`")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append(
                f"**Sujet** `{_esc(before.topic or '—', 200)}` → `{_esc(after.topic or '—', 200)}`"
            )
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            changes.append(f"**Slowmode** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
            changes.append(f"**NSFW** `{before.nsfw}` → `{after.nsfw}`")

        b_over = {str(getattr(k, "id", k)): v for k, v in before.overwrites.items()}
        a_over = {str(getattr(k, "id", k)): v for k, v in after.overwrites.items()}
        if b_over != a_over:
            targets = []
            for k in set(b_over) | set(a_over):
                if b_over.get(k) == a_over.get(k):
                    continue
                try:
                    key = int(k)
                except (TypeError, ValueError):
                    targets.append(k)
                    continue
                target = after.guild.get_role(key) or after.guild.get_member(key)
                targets.append(target.mention if target else f"`{k}`")
            if targets:
                changes.append("**Permissions modifiées** " + ", ".join(targets[:15]))

        if not changes:
            return
        await loghub.log(
            after.guild, "channels",
            f"## 🛠️ Salon modifié — {after.mention}\n" + "\n".join(changes),
        )

    # ── Rôles ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await loghub.log(
            role.guild, "roles",
            "## 🎭 Rôle créé\n"
            f"**Nom** {role.mention} (`{role.name}`)\n"
            f"**Couleur** `{role.colour}` · **Mentionnable** `{role.mentionable}`\n"
            f"**ID** `{role.id}`",
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await loghub.log(
            role.guild, "roles",
            "## 🎭 Rôle supprimé\n"
            f"**Nom** `{role.name}` · **Couleur** `{role.colour}` · **ID** `{role.id}`\n"
            f"**Membres concernés** `{len(role.members)}`",
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** `{before.name}` → `{after.name}`")
        if before.colour != after.colour:
            changes.append(f"**Couleur** `{before.colour}` → `{after.colour}`")
        if before.hoist != after.hoist:
            changes.append(f"**Affiché séparément** `{before.hoist}` → `{after.hoist}`")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionnable** `{before.mentionable}` → `{after.mentionable}`")
        if before.permissions != after.permissions:
            gained = [p for p, v in after.permissions if v and not getattr(before.permissions, p, False)]
            lost   = [p for p, v in before.permissions if v and not getattr(after.permissions, p, False)]
            danger = [p for p in gained if p in _DANGEROUS_PERMS]
            if gained:
                changes.append("**Permissions ajoutées** " + ", ".join(f"`{p}`" for p in gained[:15]))
            if lost:
                changes.append("**Permissions retirées** " + ", ".join(f"`{p}`" for p in lost[:15]))
            if danger:
                changes.append("🚨 **Permissions sensibles** " + ", ".join(f"`{p}`" for p in danger))
        if not changes:
            return
        await loghub.log(
            after.guild, "roles",
            f"## 🎭 Rôle modifié — {after.mention}\n" + "\n".join(changes),
        )

    # ── Fils ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        await loghub.log(
            thread.guild, "threads",
            "## 🧵 Fil créé\n"
            f"**Nom** {thread.mention} (`{thread.name}`)\n"
            f"**Salon parent** {thread.parent.mention if thread.parent else '?'}\n"
            f"**Créé par** {thread.owner.mention if thread.owner else '?'}",
        )

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        await loghub.log(
            thread.guild, "threads",
            "## 🧵 Fil supprimé\n"
            f"**Nom** `{thread.name}` · **ID** `{thread.id}`\n"
            f"**Salon parent** {thread.parent.mention if thread.parent else '?'}",
        )

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** `{before.name}` → `{after.name}`")
        if before.archived != after.archived:
            changes.append("**Archivé**" if after.archived else "**Désarchivé**")
        if before.locked != after.locked:
            changes.append("**Verrouillé**" if after.locked else "**Déverrouillé**")
        if not changes:
            return
        await loghub.log(
            after.guild, "threads",
            f"## 🧵 Fil modifié — {after.mention}\n" + "\n".join(changes),
        )

    # ── Invitations ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        await loghub.log(
            invite.guild, "invites",
            "## 🔗 Invitation créée\n"
            f"**Code** `{invite.code}` — discord.gg/{invite.code}\n"
            f"**Par** {invite.inviter.mention if invite.inviter else '?'} "
            f"(`{invite.inviter.id if invite.inviter else '?'}`)\n"
            f"**Salon** {invite.channel.mention if invite.channel else '?'}\n"
            f"**Expire** {'jamais' if not invite.max_age else f'{invite.max_age}s'}"
            f" · **Utilisations max** {invite.max_uses or '∞'}"
            f" · **Temporaire** `{invite.temporary}`",
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        await loghub.log(
            invite.guild, "invites",
            "## 🔗 Invitation supprimée\n"
            f"**Code** `{invite.code}`\n"
            f"**Salon** {invite.channel.mention if invite.channel else '?'}",
        )

    # ── Modération ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        try:
            entry = await guild.fetch_ban(user)
            reason = entry.reason or "aucune raison"
        except Exception:
            reason = "inconnue"
        await loghub.log(
            guild, "moderation",
            "## 🔨 Bannissement\n"
            f"**Utilisateur** `{user}` (`{user.id}`)\n"
            f"**Raison** {_esc(reason, 300)}",
            thumbnail=str(user.display_avatar.url),
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await loghub.log(
            guild, "moderation",
            "## ✅ Débannissement\n"
            f"**Utilisateur** `{user}` (`{user.id}`)",
            thumbnail=str(user.display_avatar.url),
        )

    # ── Webhooks / serveur ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        try:
            webhooks = await channel.webhooks()
        except discord.HTTPException:
            webhooks = []
        names = ", ".join(f"`{w.name}`" for w in webhooks) or "aucun"
        await loghub.log(
            channel.guild, "server",
            "## 🪝 Webhooks modifiés\n"
            f"**Salon** {channel.mention}\n**Webhooks** {names}",
        )

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"**Nom** `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Icône** modifiée")
        if before.banner != after.banner:
            changes.append("**Bannière serveur** modifiée")
        if before.description != after.description:
            changes.append("**Description** modifiée")
        if before.verification_level != after.verification_level:
            changes.append(f"**Niveau de vérification** `{before.verification_level}` → `{after.verification_level}`")
        if before.premium_tier != after.premium_tier:
            changes.append(f"**Palier de boosts** `{before.premium_tier}` → `{after.premium_tier}`")
        if before.owner_id != after.owner_id:
            changes.append(f"**Propriétaire** <@{before.owner_id}> → <@{after.owner_id}>")
        if not changes:
            return
        await loghub.log(after, "server", "## ⚙️ Serveur modifié\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list, after: list):
        added   = [e for e in after if e not in before]
        removed = [e for e in before if e not in after]
        if added:
            await loghub.log(
                guild, "server",
                "## 😄 Émoji(s) ajouté(s)\n" + " ".join(str(e) for e in added)
                + "\n" + " ".join(f"`{e.name}`" for e in added),
                gallery=[(str(e.url), e.name) for e in added[:5]],
            )
        if removed:
            await loghub.log(
                guild, "server",
                "## 😢 Émoji(s) supprimé(s)\n" + ", ".join(f"`{e.name}`" for e in removed),
            )

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before: list, after: list):
        added   = [s for s in after if s not in before]
        removed = [s for s in before if s not in after]
        if added or removed:
            parts = []
            if added:
                parts.append("**Ajoutés** " + ", ".join(f"`{s.name}`" for s in added))
            if removed:
                parts.append("**Supprimés** " + ", ".join(f"`{s.name}`" for s in removed))
            await loghub.log(guild, "server", "## 🩹 Stickers modifiés\n" + "\n".join(parts))

    # ── Journal d'audit Discord (qui a fait quoi) ───────────────────────────

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        target = ""
        try:
            if isinstance(entry.target, (discord.Member, discord.User)):
                target = f"{entry.target.mention} (`{entry.target.id}`)"
            elif isinstance(entry.target, discord.abc.GuildChannel):
                target = f"{entry.target.mention} (`{entry.target.id}`)"
            elif isinstance(entry.target, discord.Role):
                target = f"{entry.target.mention} (`{entry.target.id}`)"
            elif entry.target is not None:
                target = f"`{entry.target}` (`{getattr(entry.target, 'id', '?')}`)"
        except Exception:
            target = "?"

        changes = []
        if entry.changes:
            try:
                for attr, values in entry.changes.before.__dict__.items():  # type: ignore[attr-defined]
                    after_val = getattr(entry.changes.after, attr, None)  # type: ignore[attr-defined]
                    if values != after_val:
                        changes.append(f"`{attr}`: `{values}` → `{after_val}`")
            except Exception:
                pass

        await loghub.log(
            guild, "audit",
            "## 🕵️ Entrée d'audit\n"
            f"**Action** `{entry.action.name}`\n"
            f"**Par** {entry.user.mention if entry.user else '?'} "
            f"(`{getattr(entry.user, 'id', '?')}`)\n"
            f"**Cible** {target or '—'}\n"
            f"**Raison** {_esc(entry.reason or '—', 200)}"
            + (("\n**Changements** " + " · ".join(changes[:8])) if changes else ""),
            thumbnail=str(entry.user.display_avatar.url) if entry.user else None,
        )

    # ── Commandes ───────────────────────────────────────────────────────────

    @commands.Cog.listener("on_app_command_completion")
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command | app_commands.ContextMenu,
    ):
        guild = interaction.guild
        if guild is None:
            return
        loghub.bump(guild.id, "commands", user_id=interaction.user.id,
                    channel_id=getattr(interaction.channel, "id", None))

        options = ""
        try:
            ns = interaction.namespace
            pairs = []
            for name in vars(ns):
                if name.startswith("_"):
                    continue
                value = getattr(ns, name)
                if value is None:
                    continue
                pairs.append(f"`{name}`={_esc(str(value), 120)}")
            if pairs:
                options = "\n**Options** " + " · ".join(pairs[:10])
        except Exception:
            pass

        duration = ""
        try:
            ms = int((datetime.now(timezone.utc) - interaction.created_at).total_seconds() * 1000)
            duration = f" · `{ms} ms`"
        except Exception:
            pass

        await loghub.log(
            guild, "commands",
            "## ⌨️ Commande utilisée\n"
            f"**Membre** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"**Commande** `/{command.qualified_name}`{duration}\n"
            f"**Salon** {interaction.channel.mention if interaction.channel else '?'}{options}",
            thumbnail=str(interaction.user.display_avatar.url),
        )

    @commands.Cog.listener("on_app_command_error")
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError,
    ):
        guild = interaction.guild
        if guild is None:
            return
        original = getattr(error, "original", error)
        await loghub.log(
            guild, "commands",
            "## ⚠️ Commande en erreur\n"
            f"**Membre** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"**Commande** `/{getattr(interaction.command, 'qualified_name', '?')}`\n"
            f"**Salon** {interaction.channel.mention if interaction.channel else '?'}\n"
            f"**Erreur** `{type(original).__name__}` — {_esc(str(original), 300)}",
            thumbnail=str(interaction.user.display_avatar.url),
        )

    # ── Rapport périodique ──────────────────────────────────────────────────

    @tasks.loop(hours=6)
    async def digest_loop(self):
        try:
            for guild in self.bot.guilds:
                await self._send_digest(guild)
        except Exception as e:
            log.error("digest_loop: %s", e)

    @digest_loop.before_loop
    async def _before_digest(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(600)  # laisse le temps au démarrage

    async def _send_digest(self, guild: discord.Guild) -> None:
        today  = loghub.day_stats(guild.id)
        rows   = loghub.history(guild.id, days=2)
        if len(rows) >= 2:
            _, yesterday = rows[-2]
            messages_delta = today["messages"] - yesterday.get("messages", 0)
            joins_delta    = today["joins"] - yesterday.get("joins", 0)
            delta = (
                f"\n**Comparé à hier** messages `{messages_delta:+d}`"
                f" · arrivées `{joins_delta:+d}`"
            )
        else:
            delta = ""

        humans = sum(1 for m in guild.members if not m.bot)
        online = sum(
            1 for m in guild.members
            if not m.bot and m.status != discord.Status.offline
        )

        top_channels = loghub.top_entries(today.get("channels"), 5)
        top_users    = loghub.top_entries(today.get("users"), 5)

        def format_channels(rows_):
            out = []
            for cid, count in rows_:
                ch = guild.get_channel(int(cid))
                out.append(f"• {ch.mention if ch else f'`{cid}`'} — **{count}** messages")
            return "\n".join(out) or "*aucune donnée*"

        def format_users(rows_):
            out = []
            for uid, count in rows_:
                m = guild.get_member(int(uid))
                out.append(f"• {m.mention if m else f'`{uid}`'} — **{count}** messages")
            return "\n".join(out) or "*aucune donnée*"

        content = (
            "## 📊 Rapport — "
            f"{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC\n"
            f"**Membres** `{guild.member_count}` · humains `{humans}` · en ligne `{online}`\n"
            f"**Boosts** `{guild.premium_subscription_count}` (palier `{guild.premium_tier}`){delta}\n"
            "### Aujourd'hui\n"
            f"💬 Messages `{today['messages']}` · ✏️ Éditions `{today['edits']}`"
            f" · 🗑️ Suppressions `{today['deletes']}`\n"
            f"⌨️ Commandes `{today['commands']}` · 📥 Arrivées `{today['joins']}`"
            f" · 📤 Départs `{today['leaves']}` · 🚪 Invitations `{today.get('invites', 0)}`\n"
            f"🔊 Vocal `{today.get('voice_seconds', 0) // 60}` min\n"
            f"🔨 Modération `{today.get('moderation', 0)}`"
            f" · 🚨 Sécurité `{today.get('spam', 0)}`\n\n"
            f"### Top salons\n{format_channels(top_channels)}\n\n"
            f"### Top membres\n{format_users(top_users)}"
        )
        await loghub.log(guild, "stats", content)

    # ── Commandes admin ─────────────────────────────────────────────────────

    @app_commands.command(
        name="logssetup",
        description="Crée la catégorie privée et les salons de logs (accès restreint).",
    )
    @app_commands.describe(
        recreer="Supprimer puis recréer les salons de logs (l'historique des logs est perdu)",
        nom_categorie="Nom de la catégorie (défaut : logs)",
    )
    @app_commands.guild_only()
    @log_access_only()
    async def logssetup(
        self,
        interaction: discord.Interaction,
        recreer: bool = False,
        nom_categorie: str = "logs",
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return

        try:
            mapping, created, reused = await loghub.ensure_channels(
                guild, recreate=recreer, category_name=nom_categorie[:100] or "logs",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I need the **Manage Channels** permission to create the log channels.",
                ephemeral=True,
            )
            return

        role = guild.get_role(LOG_ACCESS_ROLE_ID)
        role_line = (
            f"**Accès** {role.mention} (`{role.id}`) — « Voir le salon » uniquement"
            if role else
            f"⚠️ **Rôle d'accès introuvable** (`{LOG_ACCESS_ROLE_ID}`) — ajoute-le vite, "
            "sinon personne ne verra les logs."
        )

        await loghub.log(
            guild, "bot",
            "## 🛠️ Installation des logs\n"
            f"**Par** {interaction.user.mention}\n"
            f"**Salons** `{len(mapping)}` configurés\n"
            f"{role_line}",
        )

        preview_created = "\n".join(created[:20]) or "*aucun*"
        preview_reused  = "\n".join(reused[:20]) or "*aucun*"

        await interaction.followup.send(
            "✅ **Système de logs installé !**\n\n"
            f"{role_line}\n"
            f"**Catégorie** <#{loghub.category_id()}> · **{len(mapping)} salons**\n\n"
            f"**Créés ({len(created)})**\n{preview_created}\n\n"
            f"**Réutilisés ({len(reused)})**\n{preview_reused}\n\n"
            "-# ⚠️ Les membres avec la permission *Administrateur* voient tous les "
            "salons (limitation Discord, impossible à contourner).\n"
            "-# Utilise `/logtoggle` pour couper un type de log et `/logstats` pour "
            "le tableau de bord.",
            ephemeral=True,
        )

    @app_commands.command(name="logtoggle", description="Activer/désactiver un type de log.")
    @app_commands.describe(type_log="Type de log à basculer.", actif="Activer ou désactiver.")
    @app_commands.choices(type_log=[
        app_commands.Choice(name=key, value=key) for key in loghub.LOG_CHANNELS
    ])
    @app_commands.guild_only()
    @log_access_only()
    async def logtoggle(
        self,
        interaction: discord.Interaction,
        type_log: app_commands.Choice[str],
        actif: bool = True,
    ):
        loghub.set_enabled(interaction.guild_id, type_log.value, actif)
        emoji = "🟢" if actif else "🔴"
        await interaction.response.send_message(
            f"{emoji} Log **{type_log.value}** {'activé' if actif else 'désactivé'}.",
            ephemeral=True,
        )

    @app_commands.command(name="logstats", description="Tableau de bord des statistiques du serveur.")
    @app_commands.guild_only()
    @log_access_only()
    async def logstats(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return
        await interaction.response.defer(ephemeral=True)

        today   = loghub.day_stats(guild.id)
        history = loghub.history(guild.id, days=7)

        humans = sum(1 for m in guild.members if not m.bot)
        bots   = guild.member_count - humans
        online = sum(1 for m in guild.members if not m.bot and m.status != discord.Status.offline)

        embed = discord.Embed(
            title="📊 Tableau de bord — renseignement",
            color=0xE67E22,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="👥 Membres",
            value=f"Total `{guild.member_count}`\nHumains `{humans}`\nBots `{bots}`\nEn ligne `{online}`",
            inline=True,
        )
        embed.add_field(
            name="📈 Aujourd'hui",
            value=(
                f"💬 Messages `{today['messages']}`\n"
                f"✏️ Éditions `{today['edits']}`\n"
                f"🗑️ Suppressions `{today['deletes']}`\n"
                f"⌨️ Commandes `{today['commands']}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="🚪 Flux",
            value=(
                f"📥 Arrivées `{today['joins']}`\n"
                f"📤 Départs `{today['leaves']}`\n"
                f"🔗 Invitations `{today.get('invites', 0)}`\n"
                f"🔊 Vocal `{today.get('voice_seconds', 0) // 60} min`"
            ),
            inline=True,
        )

        # Tendance 7 jours
        if history:
            trend = []
            for date, day in history:
                trend.append(f"`{date[5:]}` 💬{day['messages']:>5} ⌨️{day['commands']:>3} 📥{day['joins']:>2} 📤{day['leaves']:>2}")
            embed.add_field(name="🗓️ 7 derniers jours", value="\n".join(trend), inline=False)

        top_channels = loghub.top_entries(today.get("channels"), 5)
        if top_channels:
            lines = []
            for cid, count in top_channels:
                ch = guild.get_channel(int(cid))
                lines.append(f"• {ch.mention if ch else f'`{cid}`'} — **{count}** messages")
            embed.add_field(name="🏆 Salons les plus actifs", value="\n".join(lines), inline=False)

        top_users = loghub.top_entries(today.get("users"), 5)
        if top_users:
            lines = []
            for uid, count in top_users:
                m = guild.get_member(int(uid))
                lines.append(f"• {m.mention if m else f'`{uid}`'} — **{count}** messages")
            embed.add_field(name="🥇 Membres les plus actifs", value="\n".join(lines), inline=False)

        invites = db.config().get("invites", {}).get(str(guild.id), {})
        if isinstance(invites, dict) and invites:
            counts: dict[str, int] = {}
            for rec in invites.values():
                if isinstance(rec, dict) and rec.get("inviter_id"):
                    key = str(rec["inviter_id"])
                    counts[key] = counts.get(key, 0) + 1
            rows = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
            lines = []
            for uid, count in rows:
                m = guild.get_member(int(uid))
                lines.append(f"• {m.mention if m else f'`{uid}`'} — **{count}** invitation(s)")
            embed.add_field(name="🚪 Top parrains", value="\n".join(lines) or "—", inline=False)

        embed.set_footer(
            text=f"Logs : {len(loghub.channel_map())}/{len(loghub.LOG_CHANNELS)} salons configurés"
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @logssetup.error
    @logtoggle.error
    @logstats.error
    async def _log_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = (
            "❌ You don't have access to the logs commands."
            if isinstance(error, app_commands.CheckFailure)
            else f"❌ Error: `{type(error).__name__}`"
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
