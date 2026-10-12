from __future__ import annotations

import discord

from utils.emojis import E
from utils import ui
from .constants import (
    DEFAULT_LANG, TICKET_LANG_BUTTON_ID, TICKET_UI,
)


class TicketLangView(discord.ui.View):
    """Bouton « changer la langue » du message d'accueil d'un ticket.

    Une seule vue persistante pour tous les tickets (le ``custom_id`` est fixe) :
    c'est la base de données qui garde la langue courante de chaque salon.
    Le bouton traduit **tout le message du bot** (titre, guide, mentions
    d'ouverture) pour tout le monde, et son libellé bascule en même temps.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Français",
        emoji="🇫🇷",
        style=discord.ButtonStyle.secondary,
        custom_id=TICKET_LANG_BUTTON_ID,
    )
    async def switch_lang(self, interaction: discord.Interaction, button: discord.ui.Button):
        import logging

        import utils.db as db
        from utils.api import api_edit

        log = logging.getLogger(__name__)
        tickets = db.tickets()
        info = tickets.get(str(interaction.channel_id))
        if not info:
            await ui.send(interaction, ui.info_card(
                "Not a tracked ticket", "This channel isn't a ticket I created."
            ), ephemeral=True)
            return

        current = info.get("lang") or DEFAULT_LANG
        target = TICKET_UI.get(current, TICKET_UI[DEFAULT_LANG])["switch_to"]

        # L'édition du message passe par l'API brute (components v2) : on
        # acquitte tout de suite pour ne pas dépasser les 3 s règlementaires.
        await interaction.response.defer()

        info = {**info, "lang": target}
        tickets[str(interaction.channel_id)] = info
        db.save_tickets(tickets)

        from .constants import build_ticket_intro

        payload = {
            "flags": 32768,
            "components": build_ticket_intro(
                info.get("type", "question"),
                target,
                info.get("number"),
                info.get("opener_id") or interaction.user.id,
                info.get("opened_ts") or 0,
            ),
        }
        message_id = getattr(interaction.message, "id", None)
        if message_id:
            status, resp = await api_edit(interaction.channel_id, message_id, payload)
            if status not in (200, 201):
                log.error("ticket lang toggle: %s %s", status, resp)


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="close_ticket",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ask for the close reason before closing.
        # Raison de fermeture : petite carte avec les boutons de motif.
        reason_card = ui.Card("## 🔒 Closing the ticket", accent=ui.ACCENT_WARN)
        reason_card.text("Pick a reason — it helps us keep the logs meaningful.")
        for item in CloseReasonView().children:
            reason_card.container.add_item(item)
        reason_card.footer(f"Close requested by {interaction.user.display_name}")
        await ui.send(interaction, reason_card, ephemeral=True)


class CloseReasonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select a close reason…",
        options=[
            discord.SelectOption(label="✅ Resolved",  value="resolved",  description="Issue resolved"),
            discord.SelectOption(label="⏳ Abandoned", value="abandoned", description="User abandoned / no response"),
            discord.SelectOption(label="📄 Duplicate", value="duplicate", description="Duplicate of another ticket"),
        ],
    )
    async def reason_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        reason = select.values[0]
        await interaction.response.defer(ephemeral=True)
        from .core import _do_close_ticket  # local import to avoid circularity
        # On transmet l'interaction : _do_close_ticket répond via followup, sinon
        # l'éphémère "réfléchit…" restait bloqué pour l'utilisateur.
        await _do_close_ticket(interaction.channel, interaction.user, interaction, reason=reason)


class ReopenView(discord.ui.View):
    def __init__(self, number: int):
        super().__init__(timeout=None)
        self.number = number
        btn = discord.ui.Button(
            label="Reopen Ticket",
            style=discord.ButtonStyle.success,
            emoji="🔓",
            custom_id=f"reopen_ticket_{number}",
        )
        btn.callback = self.reopen
        self.add_item(btn)

    async def reopen(self, interaction: discord.Interaction):
        from .core import _reopen_ticket  # local import to avoid circularity
        await _reopen_ticket(interaction, self.number)
