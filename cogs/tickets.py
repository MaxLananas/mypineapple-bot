from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from io import StringIO

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send
from utils.helpers import ts_now, safe_add_role
from config import (
    LOGO_URL,
    TICKET_CATEGORY_ID, TICKET_LOG_CHANNEL_ID, SUPPORT_ROLE_ID,
    CLIENT_ROLE_ID, REVIEW_FORUM_ID,
)

log = logging.getLogger(__name__)


def _is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


TICKET_TYPES = {
    "commission": {
        "label":  "Commission",
        "emoji":  "🎨",
        "style":  1,
        "accent": 0x1E90FF,
        "prefix": "commission",
        "header": "# 🌊 MyPineapple Commissions\n## COMMISSION REQUEST\n_Please provide as much detail as possible._",
        "color":  discord.ButtonStyle.primary,
    },
    "bug": {
        "label":  "Bug Report",
        "emoji":  "🐛",
        "style":  2,
        "accent": 0xED4245,
        "prefix": "bug",
        "header": "# 🌊 MyPineapple Bug Reports\n## BUG REPORT\n_Please describe the issue clearly._",
        "color":  discord.ButtonStyle.secondary,
    },
    "partnership": {
        "label":  "Partnership",
        "emoji":  "🤝",
        "style":  2,
        "accent": 0x57F287,
        "prefix": "partner",
        "header": "# 🌊 MyPineapple Partnerships\n## PARTNERSHIP REQUEST\n_Tell us about your project and what you're looking for._",
        "color":  discord.ButtonStyle.secondary,
    },
    "question": {
        "label":  "Question",
        "emoji":  "❓",
        "style":  2,
        "accent": 0xF7CAC9,
        "prefix": "question",
        "header": "# 🌊 MyPineapple Support\n## GENERAL QUESTION\n_Ask us anything!_",
        "color":  discord.ButtonStyle.secondary,
    },
}


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
        await _do_close_ticket(interaction.channel, interaction.user, interaction)


async def _do_close_ticket(
    channel:     discord.TextChannel,
    closed_by:   discord.Member,
    interaction: discord.Interaction | None = None,
):
    tickets = db.tickets()
    info    = tickets.get(str(channel.id), {})
    ts      = ts_now()

    logs = db.ticketlogs().get(str(channel.id), [])
    transcript_file = None
    if logs:
        logs = list(logs) + [
            "─" * 48,
            "[TICKET CLOSED]",
            f"Closed by : {closed_by} ({closed_by.id})",
            f"Date      : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ]
        buf = StringIO("\n".join(logs))
        transcript_file = discord.File(buf, filename=f"transcript-{channel.name}.txt")

    log_ch = channel.guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if log_ch and info:
        await api_send(log_ch.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xED4245,
                    "components": [
                        {
                            "type": 10,
                            "content": (
                                f"## Ticket Closed\n"
                                f"**Type** {info.get('type', '?').capitalize()}\n"
                                f"**Channel** `{channel.name}`\n"
                                f"**Opened by** <@{info.get('opener_id')}>\n"
                                f"**Closed by** {closed_by.mention}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        }
                    ],
                }
            ],
        })
        if transcript_file:
            await log_ch.send(content=f"Transcript — `{channel.name}`", file=transcript_file)

    if interaction:
        await interaction.response.send_message("Closing in 5 seconds…")
    else:
        await channel.send("Closing in 5 seconds…")

    await asyncio.sleep(5)

    if str(channel.id) in tickets:
        del tickets[str(channel.id)]
        db.save_tickets(tickets)

    tlogs = db.ticketlogs()
    if str(channel.id) in tlogs:
        del tlogs[str(channel.id)]
        db.save_ticketlogs(tlogs)

    try:
        await channel.delete(reason=f"Closed by {closed_by}")
    except Exception as e:
        log.error("Ticket delete: %s", e)


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


async def _create_ticket(
    interaction: discord.Interaction,
    kind:        str,
    body:        str,
    image_url:   str | None,
) -> discord.TextChannel:
    guild        = interaction.guild
    member       = interaction.user
    category     = guild.get_channel(TICKET_CATEGORY_ID)
    support_role = guild.get_role(SUPPORT_ROLE_ID)
    type_info    = TICKET_TYPES[kind]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            manage_channels=True, manage_messages=True,
        ),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_messages=True,
        )

    # Nettoie le pseudo : minuscules, alphanum + tiret/underscore, max 18 chars.
    safe = "".join(
        c if c.isalnum() or c in ("-", "_") else "-"
        for c in member.name.lower()
    ).strip("-")[:18] or "user"
    channel = await guild.create_text_channel(
        name=f"{type_info['prefix']}-{safe}",
        category=category,
        overwrites=overwrites,
        topic=f"{kind} | {member} ({member.id})",
    )

    tickets = db.tickets()
    tickets[str(channel.id)] = {
        "type":       kind,
        "opener_id":  member.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_tickets(tickets)

    tlogs = db.ticketlogs()
    tlogs[str(channel.id)] = [
        "[TICKET OPENED]",
        f"Type    : {kind}",
        f"User    : {member} ({member.id})",
        f"Channel : {channel.name} ({channel.id})",
        f"Date    : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "─" * 48,
    ]
    db.save_ticketlogs(tlogs)

    ts = ts_now()
    components_inner = [
        {
            "type": 9,
            "components": [{"type": 10, "content": type_info["header"]}],
            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
        },
        {"type": 14, "divider": True, "spacing": 1},
        {"type": 10, "content": body},
    ]

    if image_url:
        components_inner.append({
            "type": 12,
            "items": [{"media": {"url": image_url}, "description": "Attached reference"}],
        })

    components_inner += [
        {"type": 14, "divider": True, "spacing": 1},
        {
            "type": 10,
            "content": f"**Opened by** {member.mention}\n**Opened at** <t:{ts}:F>",
        },
    ]

    await api_send(channel.id, {
        "flags": 32768,
        "components": [
            {"type": 17, "accent_color": type_info["accent"], "components": components_inner}
        ],
    })

    ping = member.mention + (f" {support_role.mention}" if support_role else "")
    await channel.send(content=ping, view=CloseTicketView())

    log_ch = guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if log_ch:
        await api_send(log_ch.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x57F287,
                    "components": [
                        {
                            "type": 10,
                            "content": (
                                f"## Ticket Opened\n"
                                f"**Type** {kind.capitalize()}\n"
                                f"**Channel** {channel.mention}\n"
                                f"**User** {member.mention} (`{member.id}`)\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        }
                    ],
                }
            ],
        })

    return channel


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(CloseTicketView())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if str(message.channel.id) in db.tickets():
            ts     = datetime.now(timezone.utc).strftime("%H:%M:%S")
            tlogs  = db.ticketlogs()
            entry  = tlogs.get(str(message.channel.id)) or []
            line   = f"[{ts}] {message.author} ({message.author.id}): {message.content}"
            if message.attachments:
                line += " | attachments: " + ", ".join(a.url for a in message.attachments)
            entry.append(line)
            tlogs[str(message.channel.id)] = entry
            db.save_ticketlogs(tlogs)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id", "")
        if cid in _MODAL_MAP:
            await _gate_ticket(interaction, cid)

    @app_commands.command(name="ticket-panel", description="Send the ticket panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        status, resp = await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x1E90FF,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": (
                                        "# 🌊 MyPineapple Support\n"
                                        "Choose a category below to open a ticket.\n"
                                        "Our team will get back to you as soon as possible."
                                    ),
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                "🎨 **Commission** — Want a custom build, plugin or mod?\n"
                                "🐛 **Bug Report** — Found something broken? Let us know.\n"
                                "🤝 **Partnership** — Want to collaborate with us?\n"
                                "❓ **Question** — Any other question? We're here."
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 1,
                                    "label": "Commission",
                                    "emoji": {"name": "🎨"},
                                    "custom_id": "ticket_commission",
                                },
                                {
                                    "type": 2,
                                    "style": 2,
                                    "label": "Bug Report",
                                    "emoji": {"name": "🐛"},
                                    "custom_id": "ticket_bug",
                                },
                                {
                                    "type": 2,
                                    "style": 2,
                                    "label": "Partnership",
                                    "emoji": {"name": "🤝"},
                                    "custom_id": "ticket_partnership",
                                },
                                {
                                    "type": 2,
                                    "style": 2,
                                    "label": "Question",
                                    "emoji": {"name": "❓"},
                                    "custom_id": "ticket_question",
                                },
                            ],
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": "-# You can attach a screenshot or reference image directly in the form. 🍍",
                        },
                    ],
                }
            ],
        })
        msg = "✓ Panel sent!" if status in (200, 201) else f"✗ `{status}`: {resp}"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="commission-close", description="Close a commission ticket and notify the client.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        delivery_message="Message to send to the client about the delivery.",
        delivery_url="Optional link to delivery (file, drive, etc.).",
    )
    async def commission_close(
        self,
        interaction: discord.Interaction,
        delivery_message: str,
        delivery_url: str | None = None,
    ):
        channel = interaction.channel
        tickets = db.tickets()
        info    = tickets.get(str(channel.id))

        if not info:
            await interaction.response.send_message(
                "This channel is not a tracked ticket.", ephemeral=True
            )
            return

        if info.get("type") != "commission":
            await interaction.response.send_message(
                "This command is only for commission tickets.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        opener_id   = info.get("opener_id")
        ts          = ts_now()
        guild       = interaction.guild
        opener      = guild.get_member(opener_id) or await guild.fetch_member(opener_id)
        client_role = guild.get_role(CLIENT_ROLE_ID)

        delivery_components = [
            {
                "type": 17,
                "accent_color": 0x57F287,
                "components": [
                    {
                        "type": 9,
                        "components": [
                            {
                                "type": 10,
                                "content": (
                                    f"## ✅ Commission Delivered!\n"
                                    f"Your commission has been completed, {opener.mention}."
                                ),
                            }
                        ],
                        "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                    },
                    {"type": 14, "divider": True, "spacing": 1},
                    {"type": 10, "content": delivery_message},
                ],
            }
        ]

        if delivery_url and _is_valid_url(delivery_url):
            delivery_components[0]["components"].append({
                "type": 10,
                "content": f"**Delivery link** — {delivery_url}",
            })

        delivery_components[0]["components"] += [
            {"type": 14, "divider": True, "spacing": 1},
            {
                "type": 10,
                "content": (
                    f"**Delivered by** {interaction.user.mention}\n"
                    f"**At** <t:{ts}:F>\n\n"
                    f"⭐ If you enjoyed the work, please leave a review with `/review` — it means a lot! 🍍"
                ),
            },
        ]

        await api_send(channel.id, {"flags": 32768, "components": delivery_components})

        if opener:
            try:
                dm = await opener.create_dm()
                dm_components = [
                    {
                        "type": 17,
                        "accent_color": 0x57F287,
                        "components": [
                            {
                                "type": 9,
                                "components": [
                                    {
                                        "type": 10,
                                        "content": (
                                            f"## ✅ Your commission is ready!\n"
                                            f"Hey **{opener.display_name}**, your commission on **MyPineapple** has been delivered!"
                                        ),
                                    }
                                ],
                                "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                            },
                            {"type": 14, "divider": True, "spacing": 1},
                            {"type": 10, "content": delivery_message},
                        ],
                    }
                ]

                if delivery_url and _is_valid_url(delivery_url):
                    dm_components[0]["components"].append({
                        "type": 10,
                        "content": f"**Delivery link** — {delivery_url}",
                    })

                dm_components[0]["components"] += [
                    {"type": 14, "divider": True, "spacing": 1},
                    {
                        "type": 10,
                        "content": (
                            f"**At** <t:{ts}:F>\n\n"
                            f"⭐ Enjoyed the work? Use `/review` on the server to leave a review — it really helps! 🍍"
                        ),
                    },
                ]

                await api_send(dm.id, {"flags": 32768, "components": dm_components})
                log.info("Delivery DM sent to %s", opener)
            except discord.Forbidden:
                log.warning("Cannot DM %s, DMs disabled.", opener)

        await interaction.followup.send(
            f"✓ Delivery message sent. Ticket closing in 10 seconds…", ephemeral=True
        )
        await asyncio.sleep(10)
        await _do_close_ticket(channel, interaction.user)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))