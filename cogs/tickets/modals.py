from __future__ import annotations

import logging

import discord

import utils.db as db
from utils.helpers import safe_add_role
from config import CLIENT_ROLE_ID

from .constants import _is_valid_url

log = logging.getLogger(__name__)


class CommissionModal(discord.ui.Modal, title="Commission Request"):
    need = discord.ui.TextInput(
        label="What do you need?",
        style=discord.TextStyle.short,
        max_length=200,
    )
    description = discord.ui.TextInput(
        label="Full description",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    deadline = discord.ui.TextInput(
        label="Deadline (if any)",
        style=discord.TextStyle.short,
        required=False,
        max_length=100,
    )
    budget = discord.ui.TextInput(
        label="Budget (if applicable)",
        style=discord.TextStyle.short,
        required=False,
        max_length=100,
    )
    reference_url = discord.ui.TextInput(
        label="Reference image URL (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="https://imgur.com/...",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from .core import _create_ticket  # local import to avoid circularity
        await interaction.response.defer(ephemeral=True)
        img       = self.reference_url.value.strip() if self.reference_url.value else None
        valid_img = img if img and _is_valid_url(img) else None
        body      = (
            f"**What do you need?**\n{self.need.value}\n\n"
            f"**Full description**\n{self.description.value}\n\n"
            f"**Deadline**\n{self.deadline.value or 'No deadline'}\n\n"
            f"**Budget**\n{self.budget.value or 'Not specified'}"
        )
        ch = await _create_ticket(interaction, "commission", body, valid_img)

        client_role = interaction.guild.get_role(CLIENT_ROLE_ID)
        if client_role:
            await safe_add_role(interaction.user, client_role, reason="Commission ticket opened")

        await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("CommissionModal: %s", error)


class BugModal(discord.ui.Modal, title="Bug Report"):
    what = discord.ui.TextInput(
        label="What is the bug?",
        style=discord.TextStyle.short,
        placeholder="Describe the bug in one sentence…",
        max_length=200,
    )
    steps = discord.ui.TextInput(
        label="Steps to reproduce",
        style=discord.TextStyle.paragraph,
        placeholder="1. Go to…\n2. Click on…\n3. See error…",
        max_length=500,
    )
    expected = discord.ui.TextInput(
        label="Expected result",
        style=discord.TextStyle.short,
        max_length=200,
    )
    actual = discord.ui.TextInput(
        label="Actual result",
        style=discord.TextStyle.short,
        max_length=200,
    )
    screenshot_url = discord.ui.TextInput(
        label="Screenshot URL (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="https://imgur.com/...",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from .core import _create_ticket  # local import to avoid circularity
        await interaction.response.defer(ephemeral=True)
        img       = self.screenshot_url.value.strip() if self.screenshot_url.value else None
        valid_img = img if img and _is_valid_url(img) else None
        body      = (
            f"**What is the bug?**\n{self.what.value}\n\n"
            f"**Steps to reproduce**\n{self.steps.value}\n\n"
            f"**Expected result**\n{self.expected.value}\n\n"
            f"**Actual result**\n{self.actual.value}"
        )
        ch = await _create_ticket(interaction, "bug", body, valid_img)
        await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("BugModal: %s", error)


class PartnershipModal(discord.ui.Modal, title="Partnership Request"):
    project = discord.ui.TextInput(
        label="Your project / server name",
        style=discord.TextStyle.short,
        max_length=200,
    )
    description = discord.ui.TextInput(
        label="What is your project about?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    offer = discord.ui.TextInput(
        label="What do you offer in return?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    contact = discord.ui.TextInput(
        label="Best way to reach you",
        style=discord.TextStyle.short,
        placeholder="Discord tag, email, website…",
        max_length=200,
    )
    link = discord.ui.TextInput(
        label="Link (website, Discord, social…)",
        style=discord.TextStyle.short,
        required=False,
        max_length=300,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from .core import _create_ticket  # local import to avoid circularity
        await interaction.response.defer(ephemeral=True)
        body = (
            f"**Project / Server**\n{self.project.value}\n\n"
            f"**Description**\n{self.description.value}\n\n"
            f"**What they offer**\n{self.offer.value}\n\n"
            f"**Contact**\n{self.contact.value}\n\n"
            f"**Link**\n{self.link.value or 'Not provided'}"
        )
        ch = await _create_ticket(interaction, "partnership", body, None)
        await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("PartnershipModal: %s", error)


class QuestionModal(discord.ui.Modal, title="General Question"):
    question = discord.ui.TextInput(
        label="Your question",
        style=discord.TextStyle.paragraph,
        placeholder="Ask us anything…",
        max_length=1000,
    )
    context = discord.ui.TextInput(
        label="Additional context (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from .core import _create_ticket  # local import to avoid circularity
        await interaction.response.defer(ephemeral=True)
        body = (
            f"**Question**\n{self.question.value}\n\n"
            f"**Additional context**\n{self.context.value or 'None'}"
        )
        ch = await _create_ticket(interaction, "question", body, None)
        await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("QuestionModal: %s", error)


_MODAL_MAP = {
    "ticket_commission":  CommissionModal,
    "ticket_bug":         BugModal,
    "ticket_partnership": PartnershipModal,
    "ticket_question":    QuestionModal,
}

_KIND_MAP = {
    "ticket_commission":  "commission",
    "ticket_bug":         "bug",
    "ticket_partnership": "partnership",
    "ticket_question":    "question",
}


async def _gate_ticket(interaction: discord.Interaction, custom_id: str):
    kind    = _KIND_MAP.get(custom_id, "question")
    tickets = db.tickets()
    uid     = interaction.user.id
    for info in tickets.values():
        if info.get("opener_id") == uid and info.get("type") == kind:
            await interaction.response.send_message(
                "You already have an open ticket of this type.", ephemeral=True
            )
            return
    modal_cls = _MODAL_MAP.get(custom_id, QuestionModal)
    await interaction.response.send_modal(modal_cls())
