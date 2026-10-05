from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import signal
import sys
import traceback

import discord
from discord.ext import commands

import utils.db as db
import utils.antispam as antispam
from utils.api import (
    init_session,
    close_session,
    start_queue_worker,
    stop_queue_worker,
)
from config import TOKEN

os.makedirs("logs", exist_ok=True)


class JsonFormatter(logging.Formatter):
    """Structured JSON log lines (one JSON object per line)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc"] = traceback.format_exception(*record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Structured JSON to file (rotating).
    json_handler = logging.handlers.RotatingFileHandler(
        "logs/bot.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    json_handler.setFormatter(JsonFormatter())

    # Human-readable stream for local/dev output.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root.handlers = [json_handler, stream_handler]


_setup_logging()
log = logging.getLogger("main")

# Intents:
#  - members          → join/leave/update (welcome, auto-role, logs)
#  - message_content  → transcripts, snipe, message logs
#  - presences        → custom status / activity logs + "online" counter
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.leveling",
    "cogs.tickets",
    "cogs.moderation",
    "cogs.fun",
    "cogs.profile",
    "cogs.info",
    "cogs.welcome",
    "cogs.logs",
    "cogs.invites",
    "cogs.help",
]


async def _load_cogs() -> None:
    """Load cogs concurrently and in isolation — one failing cog must never
    prevent the bot from booting (lazy / non-blocking load)."""
    results = await asyncio.gather(
        *(bot.load_extension(cog) for cog in COGS),
        return_exceptions=True,
    )
    for cog, res in zip(COGS, results):
        if isinstance(res, Exception):
            log.error("Cannot load %s: %s", cog, res)
        else:
            log.info("Cog loaded: %s", cog)
    _enforce_guild_only()


# Commandes volontairement utilisables en message privé. Toutes les autres sont
# marquées « serveur uniquement » : sans ça, une utilisation en DM fait planter
# la commande (`interaction.guild` vaut None → AttributeError).
DM_ALLOWED = {"help", "links", "botinfo", "ping", "8ball", "coinflip"}


def _enforce_guild_only() -> None:
    """Force ``dm_permission=False`` sur les commandes qui exigent un serveur."""
    count = 0
    for cmd in bot.tree.get_commands():
        if cmd.name in DM_ALLOWED or getattr(cmd, "guild_only", False):
            continue
        cmd.guild_only = True
        count += 1
    if count:
        log.info("Guild-only enforced on %d command(s).", count)


# Empreinte des slash-commands stockée en DB : on ne resynchronise que si le
# jeu de commandes a réellement changé.
SYNC_HASH_KEY = "command_sync_hash"


def _commands_fingerprint() -> str:
    """Empreinte (nom + description + options) de toutes les commandes.

    ``to_dict()`` exige l'arbre en paramètre (API discord.py 2.x) : oublier
    l'argument levait un TypeError attrapé plus haut, ce qui rendait le
    garde-fou inopérant et déclenchait un ``tree.sync()`` à chaque démarrage.
    """
    payload = sorted(
        json.dumps(cmd.to_dict(bot.tree), sort_keys=True, default=str)
        for cmd in bot.tree.get_commands()
    )
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()


async def _sync_commands_if_needed() -> None:
    """Synchronise les slash-commands uniquement si nécessaire.

    ``on_ready`` est rappelé à chaque reconnexion complète ; un ``tree.sync()``
    global à chaque fois peut épuiser le quota Discord (les commandes globales
    sont limitées). On compare donc une empreinte persistée en DB.
    """
    digest = ""
    try:
        digest = _commands_fingerprint()
        if digest and db.config().get(SYNC_HASH_KEY) == digest:
            log.info("Slash commands unchanged — skipping sync.")
            return
    except Exception as e:
        log.warning("command fingerprint: %s", e)

    try:
        synced = await bot.tree.sync()
        log.info("Slash commands synced: %d command(s).", len(synced))
    except Exception as e:
        log.error("tree.sync failed: %s", e)
        return

    if digest:
        try:
            cfg = db.config()
            cfg[SYNC_HASH_KEY] = digest
            db.save_config(cfg)
        except Exception as e:
            log.warning("cannot persist sync hash: %s", e)


@bot.event
async def on_ready():
    log.info("Connected as %s — %d guild(s)", bot.user, len(bot.guilds))
    await _sync_commands_if_needed()

    # 🤖 Salon de logs « bot » : premier démarrage et reconnexions.
    try:
        import utils.loghub as loghub
        first = not getattr(bot, "_boot_logged", False)
        bot._boot_logged = True
        if first:
            humans = sum(1 for g in bot.guilds for m in g.members if not m.bot)
            total = sum(g.member_count or 0 for g in bot.guilds)
            snapshot = loghub.counters_snapshot()
            await loghub.broadcast(
                "bot",
                "## 🤖 Bot démarré\n"
                f"**Compte** {bot.user} (`{getattr(bot.user, 'id', '?')}`)\n"
                f"**Serveurs** `{len(bot.guilds)}` · **Membres** `{total}` "
                f"(humains `{humans}`)\n"
                f"**Commandes** `{len(bot.tree.get_commands())}` · "
                f"**Latence** `{round(bot.latency * 1000)} ms`\n"
                f"**Logs** `{snapshot['configured']}/{snapshot['channels']}` salons "
                + ("installés ✅" if snapshot["installed"] else "— `/logssetup` à lancer ⚠️"),
            )
        else:
            await loghub.broadcast(
                "bot",
                "## 🔄 Reconnexion\n"
                f"**Latence** `{round(bot.latency * 1000)} ms` · "
                f"**Serveurs** `{len(bot.guilds)}`",
            )
    except Exception as e:
        log.warning("boot log: %s", e)


@bot.event
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    msg = "An error occurred."
    if isinstance(error, discord.app_commands.MissingPermissions):
        msg = "❌ You don't have the required permissions."
    elif isinstance(error, discord.app_commands.BotMissingPermissions):
        msg = "❌ I don't have the required permissions."
    elif isinstance(error, discord.app_commands.CommandOnCooldown):
        msg = f"⏳ Wait **{error.retry_after:.1f}s** before using this again."

    # Full traceback for diagnostics — essential in production.
    if isinstance(error, discord.app_commands.CommandInvokeError):
        log.error(
            "AppCommandError [%s]:\n%s",
            interaction.command,
            "".join(traceback.format_exception(type(error.original), error.original, error.original.__traceback__)),
        )
    else:
        log.error("AppCommandError [%s]: %s", interaction.command, error)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_error(event: str, *args, **kwargs):
    # Capture unhandled event exceptions (listeners) without crashing.
    tb = traceback.format_exc()
    log.error("Unhandled event error in '%s':\n%s", event, tb)
    try:
        import utils.loghub as loghub
        await loghub.broadcast(
            "bot",
            f"## ⚠️ Erreur non gérée — `{event}`\n```py\n{tb[-1400:]}\n```",
            accent=0xED4245,
        )
    except Exception:
        pass


def _install_signal_handlers() -> None:
    """Graceful shutdown on SIGTERM/SIGINT: stop accepting work, flush DB,
    close the aiohttp session, and exit cleanly."""
    loop = asyncio.get_event_loop()

    def _request_shutdown(signame: str) -> None:
        log.info("Received %s — shutting down gracefully…", signame)
        loop.create_task(_shutdown())

    async def _shutdown() -> None:
        try:
            await stop_queue_worker()
        except Exception as e:
            log.error("stop_queue_worker: %s", e)
        try:
            await db.flush()
            log.info("DB flushed on shutdown.")
        except Exception as e:
            log.error("flush on shutdown: %s", e)
        # Closing the bot makes bot.start() return so the finally block runs.
        if not bot.is_closed():
            await bot.close()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError):
            # Fallback for platforms without loop.add_signal_handler.
            # Bind signame as a default arg so it isn't captured late.
            signal.signal(sig, lambda *_a, _n=sig.name: _request_shutdown(_n))


async def main() -> None:
    db.setup()
    await init_session(TOKEN)
    start_queue_worker()

    _install_signal_handlers()

    async with bot:
        await db.init_db()
        await _load_cogs()
        bot.loop.create_task(db.flush_loop())

        # Rôles anti-spam à retirer suite à un restart (cf. utils/antispam.py).
        antispam.set_bot(bot)
        try:
            await antispam.restore_pending_releases()
        except Exception as e:
            log.error("antispam restore: %s", e)

        try:
            await bot.start(TOKEN)
        finally:
            await stop_queue_worker()
            await close_session()
            await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
