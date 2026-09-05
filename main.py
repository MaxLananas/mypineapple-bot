from __future__ import annotations
import asyncio
import logging
import logging.handlers
import os
import sys
import traceback

import discord
from discord.ext import commands

import utils.db as db
from utils.api import init_session, close_session
from config import TOKEN

os.makedirs("logs", exist_ok=True)
handler = logging.handlers.RotatingFileHandler(
    "logs/bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[handler, logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("main")

# Intents nécessaires :
#  - members          → join/leave/update (welcome, auto-role, logs)
#  - message_content  → transcripts, snipe, logs de messages
#  - presences        → logs de statut custom / activité + compteur "online"
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
]


@bot.event
async def on_ready():
    log.info("Connected as %s — %d guild(s)", bot.user, len(bot.guilds))
    try:
        # Sync global + par guild (plus rapide/fiable en dev). Pas de re-sync
        # systématique : seulement si une nouvelle commande est enregistrée.
        synced = await bot.tree.sync()
        log.info("Slash commands synced: %d command(s).", len(synced))
    except Exception as e:
        log.error("tree.sync failed: %s", e)


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

    # Log complet (traceback) pour le diagnostic — indispensable en prod.
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
    # Capture les exceptions non gérées des événements (listeners) sans crash.
    log.error("Unhandled event error in '%s':\n%s", event, traceback.format_exc())


async def main() -> None:
    db.setup()
    await init_session(TOKEN)

    async with bot:
        await db.init_db()

        for cog in COGS:
            try:
                await bot.load_extension(cog)
                log.info("Cog loaded: %s", cog)
            except Exception as e:
                log.error("Cannot load %s: %s", cog, e)

        bot.loop.create_task(db.flush_loop())

        try:
            await bot.start(TOKEN)
        finally:
            await close_session()
            await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())