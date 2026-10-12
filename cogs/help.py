"""Interactive /help menu — une carte navigable par catégorie.

Le menu est **public** : la réponse reste dans le salon, tout le monde voit qui
a lancé la commande et peut parcourir les catégories.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.emojis import E
from utils import ui
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

# Quelques précisions affichées sous les commandes, dans la langue du menu.
CATEGORY_HINT = {
    "leveling":   "Gagne de l'XP en discutant : les niveaux débloquent des rôles.",
    "tickets":    "Ouvre un salon privé avec l'équipe (commission, bug, recrutement…).",
    "moderation": "Commandes réservées à l'équipe — elles répondent discrètement.",
    "fun":        "Sondages, giveaways et petites pauses entre deux builds.",
    "profile":    "Ta carte de membre : niveau, portfolio, prix, inspirations.",
    "info":       "Infos sur le serveur, le bot et les liens officiels.",
    "welcome":    "Messages de bienvenue et rôles automatiques (équipe).",
    "logs":       "Journal du serveur — configuration réservée à l'équipe.",
    "invites":    "Suivi des invitations et du parrainage.",
    "help":       "Ce menu.",
}


class HelpMenu(ui.Card):
    """Carte d'aide : une catégorie à la fois, boutons de navigation."""

    def __init__(self, categories: dict[str, list], author: discord.User):
        super().__init__(accent=ui.ACCENT_INFO)
        self.categories = categories
        self.author = author
        self.current = "leveling" if "leveling" in categories else next(iter(categories))
        self.timeout = 600
        self._render()

    # ── Rendu ──
    def _render(self) -> None:
        self.container.clear_items()
        name, emoji = CATEGORY_META.get(self.current, (self.current.capitalize(), E.pineapple))
        cmds = sorted(self.categories.get(self.current, []), key=lambda c: c.name)
        total = sum(len(v) for v in self.categories.values())

        self.header(
            f"# {E.pineapple} MyPineapple — Help\n"
            f"`{total}` command(s) · `{len(self.categories)}` catégories · "
            f"niveau, tickets, build, modération…",
            thumbnail=LOGO_URL,
        )
        self.divider()

        lines = [f"### {emoji} {name}"]
        lines += [f"**`/{c.name}`** — {(c.description or 'Sans description.').strip()}"
                  for c in cmds] or ["Aucune commande dans cette catégorie."]
        hint = CATEGORY_HINT.get(self.current)
        if hint:
            lines.append(f"\n-# {hint}")
        self.text("\n".join(lines))
        self.divider(spacing=1)

        buttons = []
        for key in self.categories:
            cat_name, cat_emoji = CATEGORY_META.get(key, (key.capitalize(), E.pineapple))
            button = discord.ui.Button(
                label=cat_name,
                emoji=cat_emoji,
                style=discord.ButtonStyle.primary if key == self.current
                else discord.ButtonStyle.secondary,
                custom_id=f"help_cat_{key}",
            )
            button.callback = self._make_callback(key)
            buttons.append(button)
        for i in range(0, len(buttons), 5):
            self.row(*buttons[i:i + 5])

        self.footer(f"Menu lancé par {self.author.display_name} · "
                    f"clique une catégorie pour la consulter")

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.current = key
            self._render()
            await interaction.response.edit_message(view=self)
        return callback


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
            await ui.send(interaction, ui.warn_card(
                "Aucune commande", "Le bot n'a aucune commande à afficher pour l'instant."))
            return

        await ui.send(interaction, HelpMenu(categories, interaction.user))


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
