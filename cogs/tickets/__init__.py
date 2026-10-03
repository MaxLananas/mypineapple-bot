from __future__ import annotations

from discord.ext import commands

from .core import Tickets


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
