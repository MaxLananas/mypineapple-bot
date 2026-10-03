from __future__ import annotations

import discord

from utils.emojis import E


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
        view = CloseReasonView()
        await interaction.response.send_message(
            f"{E.question} Why are you closing this ticket?", view=view, ephemeral=True
        )


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
        await _do_close_ticket(interaction.channel, interaction.user, reason=reason)


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
