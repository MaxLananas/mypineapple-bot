"""Interactive /help menu with category buttons."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.emojis import E
from config import LOGO_URL

CATEGORY_META = {
    "leveling":   ("Leveling",   E.trophy),
    "tickets":    ("Tickets",    E.folder),
    "moderation": ("Moderation", E.shield),
    "fun":        ("Fun",        E.dice),
    "profile":    ("Profile",    E.heart),
    "info":       ("Info",       E.info),
    "welcome":    ("Welcome",    E.island),
    "logs":       ("Logs",       E.file),
    "invites":    ("Invites",    E.link),
    "help":       ("Help",       E.question),
}


class HelpMenuView(discord.ui.View):
    def __init__(self, categories: dict[str, list], author: discord.User):
        super().__init__(timeout=300)
        self.categories = categories
        self.author = author
        self.current = "leveling" if "leveling" in categories else next(iter(categories))
        for key in categories:
            name, emoji = CATEGORY_META.get(key, (key.capitalize(), E.pineapple))
            self.add_item(self._category_button(key, name, emoji))
        self._update_buttons()

    def _category_button(self, key: str, label: str, emoji: str):
        btn = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)
        btn.custom_id = f"help_cat_{key}"
        btn.callback = self._make_callback(key)
        return btn

    def _make_callback(self, key: str):
        async def cb(interaction: discord.Interaction):
            self.current = key
            self._update_buttons()
            await interaction.response.edit_message(embed=self._build_embed(), view=self)
        return cb

    def _update_buttons(self):
        for child in self.children:
            key = child.custom_id.removeprefix("help_cat_")
            child.style = (
                discord.ButtonStyle.primary if key == self.current
                else discord.ButtonStyle.secondary
            )

    def _build_embed(self) -> discord.Embed:
        name, emoji = CATEGORY_META.get(self.current, (self.current.capitalize(), E.pineapple))
        cmds = sorted(self.categories.get(self.current, []), key=lambda c: c.name)
        lines = []
        for c in cmds:
            desc = (c.description or "No description.").strip()
            lines.append(f"**`/{c.name}`** — {desc}")
        embed = discord.Embed(
            title=f"{emoji} {name} commands",
            description="\n".join(lines) or "No commands.",
            color=0x9B8EC4,
        )
        embed.set_author(name="MyPineapple Help", icon_url=LOGO_URL)
        embed.set_footer(text=f"{len(cmds)} command(s) — click a category above")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True


def _cog_category(cmd) -> str:
    """Map a command to its cog name, handling the ``cogs.tickets`` package."""
    module = getattr(cmd, "module", "other") or "other"
    if module.startswith("cogs."):
        module = module[len("cogs."):]
    return module.split(".")[0] or "other"


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Browse every command by category.")
    async def help_cmd(self, interaction: discord.Interaction):
        categories: dict[str, list] = {}
        for cmd in self.bot.tree.get_commands():
            categories.setdefault(_cog_category(cmd), []).append(cmd)

        if not categories:
            await interaction.response.send_message("No commands available.", ephemeral=True)
            return

        view = HelpMenuView(categories, interaction.user)
        await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
