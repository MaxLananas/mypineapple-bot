from __future__ import annotations

from discord.ext import commands

# Shared reference to the bot, used to register persistent views.
_bot: commands.Bot | None = None


def set_bot(bot: commands.Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> commands.Bot | None:
    return _bot
