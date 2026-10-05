"""Hub de logs « Big Brother » — salons dédiés, envoi stylisé, compteurs.

Architecture
------------
* **18 salons** dans une catégorie privée (créée par ``/logssetup``), visible
  uniquement par le rôle ``LOG_ACCESS_ROLE_ID`` (et le bot).
* Si la catégorie n'existe pas encore (ou qu'un salon a été supprimé), on
  **retombe automatiquement** sur l'ancien mode « threads dans
  ``LOG_HUB_CHANNEL_ID`` » : aucun événement n'est perdu avant l'installation.
* Les compteurs par jour (messages, commandes, joins, vocal, top salons,
  top membres…) sont persistés dans le store ``config`` → ``/logstats`` et le
  rapport périodique fonctionnent même après un restart.

Toutes les fonctions sont défensives : une erreur de log ne doit **jamais**
faire planter la commande ou l'événement qui l'a déclenchée.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import discord

import utils.db as db
from utils.api import api_send, api_send_queued
from config import LOG_HUB_CHANNEL_ID, LOG_ACCESS_ROLE_ID

logger = logging.getLogger(__name__)

CATEGORY_NAME = "logs"
DEFAULT_ACCENT = 0x9B8EC4

# key -> (nom du salon, sujet, couleur)
LOG_CHANNELS: dict[str, tuple[str, str, int]] = {
    "messages":   ("📥・messages",     "Tous les messages envoyés",                          0x5865F2),
    "edits":      ("✏️・éditions",      "Messages modifiés — avant / après",                  0xFEE75C),
    "deletes":    ("🗑️・suppressions",  "Messages supprimés — contenu et pièces jointes",     0xED4245),
    "members":    ("👥・membres",       "Arrivées, départs, pseudos",                          0x57F287),
    "profiles":   ("🖼️・profils",       "Avatar, bannière, bio, nom d'utilisateur",            0xC3B1E1),
    "status":     ("🟢・statuts",       "Statuts et activités",                                0x9B8EC4),
    "invites":    ("🚪・invitations",   "Qui invite qui, codes et sources",                    0x1ABC9C),
    "commands":   ("⌨️・commandes",     "Toutes les slash-commands utilisées",                 0xEB459E),
    "moderation": ("🔨・modération",    "Bans, kicks, timeouts, avertissements",               0xED4245),
    "roles":      ("🎭・rôles",         "Rôles : création, suppression, attribution",          0xF1C40F),
    "channels":   ("📺・salons",        "Salons, permissions, sujets",                         0x3498DB),
    "voice":      ("🔊・vocal",         "Entrées, sorties et déplacements vocaux",             0x2ECC71),
    "server":     ("⚙️・serveur",       "Serveur, émojis, boosts, webhooks",                  0x95A5A6),
    "threads":    ("🧵・fils",          "Fils de discussion",                                  0x9B59B6),
    "security":   ("🚨・sécurité",      "Nouveaux comptes, raids, anti-spam",                  0xED4245),
    "audit":      ("🕵️・audit",         "Journal d'audit Discord (qui a fait quoi)",           0x2C3E50),
    "stats":      ("📊・statistiques",  "Rapports périodiques",                                0xE67E22),
    "bot":        ("🤖・bot",           "Démarrages, erreurs, synchronisation",                0x7289DA),
}

# Compteurs jour par jour conservés (jours).
_HISTORY_DAYS = 30
# Cache mémoire : (guild_id, key) -> channel_id
_chan_cache: dict[tuple[int, str], int] = {}
# Cache mémoire : guild_id -> set(channel_ids) des salons de logs
_log_ids_cache: dict[int, set[int]] = {}

# ── Protections anti-boucle / anti-spam ─────────────────────────────────────
# 1) Pause : pendant /logssetup (création/édition des 18 salons) on ne loggue
#    pas les événements de salons, sinon on génère des dizaines de messages.
_pause_depth = 0
# 2) Débit : au-delà de _RATE_MAX envois en _RATE_WINDOW secondes sur un même
#    serveur, on coupe les logs 5 minutes. Filet de sécurité absolu : même si un
#    futur événement créait une boucle, le bot ne peut pas spammer.
_RATE_WINDOW = 10.0
_RATE_MAX = 25
_BREAKER_SECONDS = 300.0
_rate: dict[int, list[float]] = {}
_breaker_until: dict[int, float] = {}
# 3) Doublons : un même contenu vers le même salon à moins de _DEDUP_SECONDS
#    d'intervalle est ignoré (stoppe net une boucle log→message→log).
_DEDUP_SECONDS = 3.0
_last_sent: dict[tuple[int, str, str], float] = {}
# 4) Threads de secours créés par le hub : ils doivent être reconnus comme
#    salons de logs (sinon le bot reloggait ses propres logs → boucle infinie).
_fallback_threads: set[int] = set()
_PERSIST_THREADS = "log_threads"


def pause() -> None:
    """Suspend l'écriture des logs (compteur : réentrant)."""
    global _pause_depth
    _pause_depth += 1


def resume() -> None:
    global _pause_depth
    _pause_depth = max(0, _pause_depth - 1)


def is_paused() -> bool:
    return _pause_depth > 0


def _fallback_thread_ids() -> set[int]:
    ids = set(_fallback_threads)
    raw = db.config().get(_PERSIST_THREADS, [])
    if isinstance(raw, list):
        for value in raw[-200:]:
            try:
                ids.add(int(value))
            except (TypeError, ValueError):
                continue
    return ids


def remember_fallback_thread(thread_id: int) -> None:
    """Mémorise un thread de logs (mode de secours) — persisté en DB."""
    try:
        thread_id = int(thread_id)
    except (TypeError, ValueError):
        return
    _fallback_threads.add(thread_id)
    cfg = db.config()
    current = cfg.get(_PERSIST_THREADS)
    if not isinstance(current, list):
        current = []
    if thread_id not in [int(v) for v in current if str(v).lstrip("-").isdigit()]:
        current.append(thread_id)
    del current[:-200]
    cfg[_PERSIST_THREADS] = current
    db.save_config(cfg)
    _log_ids_cache.clear()


def _allow_send(guild_id: int, key: str, content: str) -> bool:
    """Filet anti-boucle : débit maximal + déduplication."""
    now = time.monotonic()
    if now < _breaker_until.get(guild_id, 0.0):
        return False

    seen = _last_sent.get((guild_id, key, content))
    if seen is not None and now - seen < _DEDUP_SECONDS:
        return False

    window = [t for t in _rate.get(guild_id, []) if now - t < _RATE_WINDOW]
    if len(window) >= _RATE_MAX:
        # Coupure automatique : quelque chose boucle, on arrête tout 5 minutes.
        _breaker_until[guild_id] = now + _BREAKER_SECONDS
        _rate[guild_id] = []
        logger.error(
            "Logs: %d messages en moins de %.0f s sur le serveur %s — écriture "
            "suspendue %.0f s (protection anti-boucle).",
            len(window), _RATE_WINDOW, guild_id, _BREAKER_SECONDS,
        )
        return False

    window.append(now)
    _rate[guild_id] = window
    _last_sent[(guild_id, key, content)] = now
    if len(_last_sent) > 5000:
        for k in sorted(_last_sent, key=_last_sent.get)[:2500]:
            _last_sent.pop(k, None)
    return True


def breaker_remaining(guild_id: int) -> float:
    """Secondes restantes de coupure anti-boucle (0 si aucun)."""
    return max(0.0, _breaker_until.get(guild_id, 0.0) - time.monotonic())


# ── Accès config ─────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return db.config()


def _save() -> None:
    db.save_config(db.config())


def category_id() -> int:
    try:
        return int(_cfg().get("log_category_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def channel_map() -> dict[str, int]:
    raw = _cfg().get("log_channels", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def save_channel_map(mapping: dict[str, int]) -> None:
    cfg = db.config()
    cfg["log_channels"] = mapping
    db.save_config(cfg)
    _chan_cache.clear()
    _log_ids_cache.clear()


def log_channel_ids(guild_id: int | None = None) -> set[int]:
    """IDs de tous les canaux de logs (pour ne **jamais** les logger).

    Inclut : la catégorie, les 18 salons mémorisés, le salon hub (mode de
    secours) et les threads de secours créés par le hub. Sans les threads, le
    bot reloggait ses propres logs et bouclait à l'infini.
    """
    if guild_id is not None:
        cached = _log_ids_cache.get(guild_id)
        if cached is not None:
            return cached
    ids = {int(v) for v in channel_map().values() if v}
    cid = category_id()
    if cid:
        ids.add(cid)
    if LOG_HUB_CHANNEL_ID:
        ids.add(int(LOG_HUB_CHANNEL_ID))
    ids |= _fallback_thread_ids()
    if guild_id is not None:
        _log_ids_cache[guild_id] = ids
    return ids


def is_log_channel(channel) -> bool:
    """Vrai si ce canal est un canal/thread de logs (donc à ne pas relogger)."""
    try:
        cid = int(getattr(channel, "id", 0) or 0)
    except Exception:
        return False
    if not cid:
        return False

    ids = log_channel_ids()
    if cid in ids:
        return True

    # Thread d'un salon de logs (ou du hub)
    parent_id = getattr(channel, "parent_id", None)
    if parent_id is not None:
        try:
            if int(parent_id) in ids:
                return True
        except (TypeError, ValueError):
            pass
    parent = getattr(channel, "parent", None)
    if parent is not None:
        try:
            if int(getattr(parent, "id", 0) or 0) in ids:
                return True
        except Exception:
            pass

    # Salon (ou thread) rangé dans la catégorie « logs »
    cid_cat = getattr(channel, "category_id", None)
    if cid_cat is None:
        cat = getattr(channel, "category", None)
        cid_cat = getattr(cat, "id", None)
    try:
        if cid_cat is not None and category_id() and int(cid_cat) == category_id():
            return True
    except (TypeError, ValueError):
        pass
    return False


# ── Activation / désactivation par type ─────────────────────────────────────

def is_enabled(guild_id: int, key: str) -> bool:
    toggles = _cfg().get("log_toggles", {})
    if isinstance(toggles, dict):
        guild = toggles.get(str(guild_id))
        if isinstance(guild, dict) and key in guild:
            return bool(guild[key])
    return True


def set_enabled(guild_id: int, key: str, value: bool) -> None:
    cfg = db.config()
    toggles = cfg.setdefault("log_toggles", {})
    toggles.setdefault(str(guild_id), {})[key] = bool(value)
    db.save_config(cfg)


def toggles_for(guild_id: int) -> dict[str, bool]:
    return {key: is_enabled(guild_id, key) for key in LOG_CHANNELS}


# ── Compteurs (stats) ────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _stats_root() -> dict:
    root = db.config().setdefault("log_stats", {})
    return root if isinstance(root, dict) else {}


def _guild_stats(guild_id: int) -> dict:
    root = _stats_root()
    g = root.setdefault(str(guild_id), {})
    if not isinstance(g, dict):
        g = root[str(guild_id)] = {}
    return g


def day_stats(guild_id: int, date: str | None = None) -> dict:
    """Compteurs d'une journée (aujourd'hui par défaut)."""
    date = date or _today()
    g = _guild_stats(guild_id)
    day = g.get(date)
    if not isinstance(day, dict):
        day = g[date] = {
            "messages": 0, "edits": 0, "deletes": 0, "commands": 0,
            "joins": 0, "leaves": 0, "invites": 0, "voice_seconds": 0,
            "users": {}, "channels": {}, "command_users": {},
        }
    day.setdefault("users", {})
    day.setdefault("channels", {})
    day.setdefault("command_users", {})
    return day


def bump(
    guild_id: int,
    event: str,
    amount: int = 1,
    *,
    user_id: int | None = None,
    channel_id: int | None = None,
) -> None:
    """Incrémente un compteur (jamais bloquant, jamais d'exception)."""
    try:
        day = day_stats(guild_id)
        if event not in ("users", "channels", "command_users"):
            day[event] = int(day.get(event, 0) or 0) + amount
        if user_id is not None:
            bucket = "command_users" if event == "commands" else "users"
            counter = day.setdefault(bucket, {})
            counter[str(user_id)] = int(counter.get(str(user_id), 0) or 0) + amount
        if channel_id is not None:
            counter = day.setdefault("channels", {})
            counter[str(channel_id)] = int(counter.get(str(channel_id), 0) or 0) + amount
        # Purge de l'historique
        g = _guild_stats(guild_id)
        if len(g) > _HISTORY_DAYS:
            for old in sorted(g)[:-_HISTORY_DAYS]:
                g.pop(old, None)
    except Exception as e:  # pragma: no cover
        logger.debug("loghub.bump(%s): %s", event, e)


def history(guild_id: int, days: int = 7) -> list[tuple[str, dict]]:
    """Les N derniers jours (du plus ancien au plus récent)."""
    g = _guild_stats(guild_id)
    dates = sorted(g)[-days:]
    return [(d, day_stats(guild_id, d)) for d in dates]


def top_entries(counter, n: int = 5) -> list[tuple[str, int]]:
    if not isinstance(counter, dict):
        return []
    rows = []
    for k, v in counter.items():
        try:
            rows.append((str(k), int(v)))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:n]


# ── Résolution des salons ────────────────────────────────────────────────────

def _overwrites(guild: discord.Guild) -> dict:
    """@everyone interdit, rôle de logs en lecture seule, bot en écriture."""
    ow: dict = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False, send_messages=False, read_message_history=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True,
            attach_files=True, read_message_history=True,
            manage_messages=True, manage_channels=True,
        ),
    }
    role = guild.get_role(LOG_ACCESS_ROLE_ID)
    if role is not None:
        ow[role] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True,
            send_messages=False, add_reactions=True,
        )
    return ow


async def ensure_channels(
    guild: discord.Guild,
    *,
    recreate: bool = False,
    category_name: str = CATEGORY_NAME,
) -> tuple[dict[str, int], list[str], list[str]]:
    """Crée (ou retrouve) la catégorie + les 18 salons de logs.

    Retourne ``(mapping, créés, réutilisés)``.
    """
    created: list[str] = []
    reused:  list[str] = []

    category = guild.get_channel(category_id()) if category_id() else None
    if category is None:
        category = discord.utils.get(guild.categories, name=category_name)
    if category is None:
        category = await guild.create_category(
            name=category_name, overwrites=_overwrites(guild),
            reason="Installation des logs (/logssetup)",
        )
        created.append(f"📁 **{category_name}** (catégorie)")
    else:
        try:
            await category.edit(overwrites=_overwrites(guild),
                                reason="Mise à jour des permissions logs")
        except discord.HTTPException as e:
            logger.warning("category overwrites: %s", e)
        reused.append(f"📁 **{category_name}** (catégorie existante)")

    cfg = db.config()
    cfg["log_category_id"] = category.id
    db.save_config(cfg)

    mapping = channel_map()

    if recreate:
        # Recréation propre : on supprime les salons de logs existants (par ID
        # mémorisé **et** par nom dans la catégorie) avant de tout reconstruire.
        doomed: list[discord.abc.GuildChannel] = []
        for cid in list(mapping.values()):
            ch = guild.get_channel(int(cid)) if cid else None
            if ch is not None:
                doomed.append(ch)
        names = {name for name, _topic, _c in LOG_CHANNELS.values()}
        for ch in category.text_channels:
            if ch.name in names and ch not in doomed:
                doomed.append(ch)
        for ch in doomed:
            try:
                await ch.delete(reason="Recréation des salons de logs (/logssetup recreer:True)")
            except discord.HTTPException as e:
                logger.warning("delete log channel %s: %s", ch.id, e)
        mapping = {}
        save_channel_map({})
        created.append(f"♻️ **{len(doomed)}** ancien(s) salon(s) supprimé(s)")

    for key, (name, topic, _colour) in LOG_CHANNELS.items():
        channel = guild.get_channel(mapping.get(key, 0)) if mapping.get(key) else None
        if channel is None:
            channel = discord.utils.get(category.text_channels, name=name)
        if channel is None:
            try:
                channel = await guild.create_text_channel(
                    name=name, category=category, topic=topic[:1024],
                    overwrites=_overwrites(guild),
                    reason="Installation des logs (/logssetup)",
                )
                created.append(channel.mention)
            except discord.HTTPException as e:
                logger.error("create log channel %s: %s", key, e)
                continue
        else:
            try:
                await channel.edit(category=category, topic=topic[:1024],
                                   overwrites=_overwrites(guild), reason="Mise à jour logs")
            except discord.HTTPException:
                pass
            reused.append(channel.mention)
        mapping[key] = channel.id

    save_channel_map(mapping)
    logger.info("Logs: %d salon(s) créé(s), %d réutilisé(s) (%s).",
             len(created), len(reused), guild.name)
    return mapping, created, reused


async def _get_thread_fallback(guild: discord.Guild, key: str) -> discord.Thread | None:
    """Ancien mode : un thread par type dans LOG_HUB_CHANNEL_ID."""
    parent = guild.get_channel(LOG_HUB_CHANNEL_ID)
    # Duck-typing : tout canal capable de créer des threads fait l'affaire
    # (TextChannel / ForumChannel…), sans dépendre d'une sous-classe précise.
    if parent is None or not hasattr(parent, "create_thread"):
        return None
    name = LOG_CHANNELS.get(key, (f"📄・{key}", "", DEFAULT_ACCENT))[0]
    for thread in list(parent.threads):
        if thread.name == name:
            remember_fallback_thread(thread.id)
            return thread
    try:
        async for thread in parent.archived_threads(limit=50):
            if thread.name == name:
                await thread.unarchive()
                remember_fallback_thread(thread.id)
                return thread
    except Exception:
        pass
    try:
        thread = await parent.create_thread(name=name, auto_archive_duration=10080,
                                            reason="Logs (mode thread)")
        remember_fallback_thread(thread.id)
        return thread
    except Exception as e:
        logger.error("thread fallback %s: %s", key, e)
        return None


async def get_destination(guild: discord.Guild, key: str):
    """Renvoie le salon (ou thread) où écrire ce type de log."""
    cached = _chan_cache.get((guild.id, key))
    if cached:
        channel = guild.get_channel(cached)
        if channel is not None:
            return channel
        _chan_cache.pop((guild.id, key), None)

    channel_id = channel_map().get(key)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            _chan_cache[(guild.id, key)] = channel.id
            return channel

    # Tentative de retrouvaille par nom dans la catégorie
    category = guild.get_channel(category_id()) if category_id() else None
    if isinstance(category, discord.CategoryChannel):
        name = LOG_CHANNELS.get(key, (key, "", DEFAULT_ACCENT))[0]
        found = discord.utils.get(category.text_channels, name=name)
        if found is not None:
            _chan_cache[(guild.id, key)] = found.id
            mapping = channel_map()
            mapping[key] = found.id
            save_channel_map(mapping)
            return found

    return await _get_thread_fallback(guild, key)


# ── Envoi ────────────────────────────────────────────────────────────────────

def _build_components(
    content: str,
    *,
    accent: int,
    gallery: list | None = None,
    thumbnail: str | None = None,
) -> list[dict]:
    header: dict = {"type": 10, "content": content[:3900]}
    if thumbnail:
        header = {
            "type": 9,
            "components": [header],
            "accessory": {"type": 11, "media": {"url": thumbnail}},
        }
    inner: list[dict] = [header]
    if gallery:
        items: list[dict] = []
        for it in gallery[:10]:
            url, desc = it if isinstance(it, tuple) else (it, None)
            entry: dict = {"media": {"url": url}}
            if desc:
                entry["description"] = desc
            items.append(entry)
        if items:
            inner.append({"type": 12, "items": items})
    return [{"type": 17, "accent_color": accent, "components": inner}]


async def log(
    guild: discord.Guild | None,
    key: str,
    content: str,
    *,
    accent: int | None = None,
    gallery: list | None = None,
    thumbnail: str | None = None,
    mentions: dict | None = None,
    queued: bool = False,
) -> None:
    """Écrit un événement dans le salon de logs correspondant.

    ``queued=True`` : envoi via la file d'attente (événements à fort volume :
    messages, éditions, suppressions) pour ne jamais ralentir le bot.
    """
    if guild is None or not content or is_paused():
        return
    try:
        if not is_enabled(guild.id, key):
            return
        if not _allow_send(guild.id, key, content):
            return
        dest = await get_destination(guild, key)
        if dest is None:
            return
        if accent is None:
            accent = LOG_CHANNELS.get(key, ("", "", DEFAULT_ACCENT))[2]
        payload = {
            "flags": 32768,
            "components": _build_components(
                content, accent=accent, gallery=gallery, thumbnail=thumbnail
            ),
        }
        if queued:
            api_send_queued(dest.id, payload, allowed_mentions=mentions)
        else:
            await api_send(dest.id, payload, allowed_mentions=mentions)
    except Exception as e:
        logger.error("loghub.log(%s): %s", key, e)


async def mod_action(
    guild: discord.Guild | None,
    action: str,
    target=None,
    moderator=None,
    *,
    reason: str = "",
    extra: str = "",
    color: int | None = None,
    thumbnail: str | None = None,
) -> None:
    """Journalise une action de modération dans ``🔨・modération``.

    Helper partagé par ``cogs/moderation.py`` (bans, kicks, mutes, warns…) et
    les listeners : une seule mise en forme, un seul compteur.
    """
    if guild is None:
        return
    target_txt = f"{getattr(target, 'mention', target)} (`{getattr(target, 'id', '?')}`)"
    mod_txt = f"{getattr(moderator, 'mention', moderator)}"
    content = (
        f"## 🔨 {action}\n"
        f"**Cible** {target_txt}\n"
        f"**Modérateur** {mod_txt}\n"
        f"**Raison** {reason or '—'}"
        + (f"\n{extra}" if extra else "")
    )
    bump(guild.id, "moderation")
    await log(guild, "moderation", content, accent=color, thumbnail=thumbnail)


async def broadcast(key: str, content: str, *, accent: int | None = None,
                    guilds=None) -> None:
    """Envoie un événement au même salon de tous les serveurs (vie du bot)."""
    try:
        import main  # import tardif : évite le cycle au chargement
        targets = guilds if guilds is not None else list(main.bot.guilds)
    except Exception:
        targets = list(guilds or [])
    for guild in targets:
        await log(guild, key, content, accent=accent)


def reset_cache() -> None:
    _chan_cache.clear()
    _log_ids_cache.clear()


def counters_snapshot() -> dict:
    return {
        "channels": len(LOG_CHANNELS),
        "configured": len(channel_map()),
        "category_id": category_id(),
        "installed": bool(channel_map()),
    }


def started_at() -> float:
    return time.time()
