from __future__ import annotations

import logging

import discord

import utils.db as db
from utils.helpers import safe_add_role
from config import CLIENT_ROLE_ID

from .constants import _is_valid_url

log = logging.getLogger(__name__)

# ── Limites imposées par l'API Discord ───────────────────────────────────────
# Les dépasser renvoie « 400 Invalid Form Body (50035) » : le modal ne s'ouvre
# JAMAIS et l'utilisateur voit « Interaction failed » (bug vécu sur le bouton
# Recruitment : un placeholder de 114 caractères > 100). On tronque donc
# systématiquement à l'envoi — un texte un peu long ne doit pas casser un bouton.
MODAL_TITLE_MAX   = 45
TEXT_LABEL_MAX    = 45
TEXT_PLACEHOLDER_MAX = 100
TEXT_VALUE_MAX    = 4000
TEXT_MIN_MAX      = 4000


def _clip(text: str | None, limit: int) -> str | None:
    """Tronque une chaîne à ``limit`` caractères (en gardant un « … » propre)."""
    if text is None:
        return None
    text = str(text)
    if not text or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _field(child):
    """Objet exposant ``label``/``placeholder``/``max_length`` du champ.

    discord.py ≥ 2.6 encapsule chaque ``TextInput`` dans un ``_underlying``
    (et déprécie ``TextInput.label``, en forçant le filtre d'avertissements :
    impossible à masquer proprement). On passe donc par l'API interne quand
    elle existe, sinon par l'ancienne — compatible 2.5 → 2.7, sans warning.
    """
    return getattr(child, "_underlying", child)


def sanitize_modal(modal: discord.ui.Modal) -> discord.ui.Modal:
    """Ramène un modal dans les limites Discord avant ``send_modal``.

    Corrige : titre > 45, label > 45, placeholder > 100, max_length > 4000,
    min_length > max_length. Une erreur ici étant invisible pour l'utilisateur
    (le formulaire ne s'affiche simplement pas), elle est aussi journalisée.
    """
    title = _clip(modal.title, MODAL_TITLE_MAX)
    if title:
        modal.title = title

    for child in list(getattr(modal, "children", []) or []):
        field = _field(child)
        label = _clip(getattr(field, "label", None), TEXT_LABEL_MAX)
        if label:
            field.label = label
        placeholder = _clip(getattr(field, "placeholder", None), TEXT_PLACEHOLDER_MAX)
        if placeholder is not None:
            field.placeholder = placeholder
        try:
            field.max_length = min(
                int(getattr(field, "max_length", TEXT_VALUE_MAX) or TEXT_VALUE_MAX),
                TEXT_VALUE_MAX,
            )
            min_length = int(getattr(field, "min_length", 0) or 0)
            if min_length > field.max_length:
                field.min_length = field.max_length
        except (TypeError, ValueError, AttributeError):
            continue
    return modal


async def _notify_error(interaction: discord.Interaction, label: str, error: Exception) -> None:
    """Prévient l'utilisateur qu'un ticket n'a pas pu être créé.

    Sans ça, une exception dans on_submit laissait le modal sur
    "Interaction failed" sans aucune explication.
    """
    log.error("%s: %s", label, error)
    msg = "❌ Something went wrong — your ticket could not be created. Please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


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
        await _notify_error(interaction, "CommissionModal", error)


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
        await _notify_error(interaction, "BugModal", error)


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
        await _notify_error(interaction, "PartnershipModal", error)


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
        await _notify_error(interaction, "QuestionModal", error)


class RecruitmentModal(discord.ui.Modal, title="Builder Recruitment"):
    pseudo = discord.ui.TextInput(
        label="Minecraft username / pseudo",
        style=discord.TextStyle.short,
        placeholder="e.g. MaxLananas",
        max_length=100,
    )
    age_country = discord.ui.TextInput(
        label="Age & country / timezone",
        style=discord.TextStyle.short,
        placeholder="e.g. 18 — France (UTC+1)",
        max_length=100,
    )
    experience = discord.ui.TextInput(
        label="Building experience",
        style=discord.TextStyle.paragraph,
        placeholder="Experience, servers/projects, styles (≤100 caractères)",
        max_length=1000,
    )
    portfolio = discord.ui.TextInput(
        label="Portfolio / screenshot links",
        style=discord.TextStyle.paragraph,
        placeholder="Imgur, Planet Minecraft, Instagram, YouTube, Google Drive…",
        max_length=500,
    )
    availability = discord.ui.TextInput(
        label="Availability & motivation",
        style=discord.TextStyle.paragraph,
        placeholder="Hours per week, when you can build, and why you want to join.",
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from .core import _create_ticket  # local import to avoid circularity
        await interaction.response.defer(ephemeral=True)
        body = (
            f"**Minecraft username**\n{self.pseudo.value}\n\n"
            f"**Age & country / timezone**\n{self.age_country.value}\n\n"
            f"**Building experience**\n{self.experience.value}\n\n"
            f"**Portfolio / screenshots**\n{self.portfolio.value}\n\n"
            f"**Availability & motivation**\n{self.availability.value}"
        )
        ch = await _create_ticket(interaction, "recruitment", body, None)
        await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await _notify_error(interaction, "RecruitmentModal", error)


_MODAL_MAP = {
    "ticket_commission":  CommissionModal,
    "ticket_recruitment": RecruitmentModal,
    "ticket_bug":         BugModal,
    "ticket_partnership": PartnershipModal,
    "ticket_question":    QuestionModal,
}

_KIND_MAP = {
    "ticket_commission":  "commission",
    "ticket_recruitment": "recruitment",
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
    modal = sanitize_modal(modal_cls())
    try:
        await interaction.response.send_modal(modal)
    except discord.HTTPException as e:
        # Un modal refusé par l'API (ex. 50035) ne doit pas rester sans réponse :
        # l'utilisateur verrait juste « Interaction failed ».
        log.error("send_modal(%s): %s", custom_id, e)
        msg = (
            "❌ I couldn't open the form (Discord refused it). "
            "Please try again, or open a ❓ Question ticket."
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
