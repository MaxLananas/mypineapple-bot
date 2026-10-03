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
from utils.helpers import ts_now
from utils.emojis import E
from config import (
    LOGO_URL,
    TICKET_CATEGORY_ID, TICKET_LOG_CHANNEL_ID, SUPPORT_ROLE_ID,
    CLIENT_ROLE_ID,
)

from . import state
from .constants import (
    _is_valid_url, TICKET_CLOSE_REASONS, TICKET_TYPES,
    _next_ticket_number, _build_overwrites,
)
from .transcript import _history_to_logs, _transcript_html, _transcript_txt
from .views import CloseTicketView, ReopenView
from .modals import _MODAL_MAP, _gate_ticket

log = logging.getLogger(__name__)


async def _do_close_ticket(
    channel:     discord.TextChannel,
    closed_by:   discord.Member,
    interaction: discord.Interaction | None = None,
    *,
    reason: str = "resolved",
):
    tickets = db.tickets()
    info    = tickets.get(str(channel.id), {})
    ts      = ts_now()

    logs = db.ticketlogs().get(str(channel.id), [])
    # Robust fallback: if in-memory logs are empty (restart, purge...),
    # rebuild the transcript from the real channel history.
    if not logs:
        logs = await _history_to_logs(channel, info)
    closed_logs = list(logs) + [
        "─" * 48,
        "[TICKET CLOSED]",
        f"Reason    : {reason}",
        f"Closed by : {closed_by} ({closed_by.id})",
        f"Date      : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
    ]

    # HTML transcript (with images) + TXT.
    html_file = discord.File(
        StringIO(_transcript_html(closed_logs, f"Transcript — {channel.name}")),
        filename=f"transcript-{channel.name}.html",
    )
    txt_file = discord.File(
        StringIO(_transcript_txt(closed_logs)),
        filename=f"transcript-{channel.name}.txt",
    )

    number = info.get("number")

    # Save the closed ticket so it can be reopened.
    if number:
        closed = db.closedtickets()
        closed[str(number)] = {
            "type":       info.get("type"),
            "opener_id":  info.get("opener_id"),
            "name":       channel.name,
            "number":     number,
            "closed_by":  closed_by.id,
            "reason":     reason,
            "closed_at":  datetime.now(timezone.utc).isoformat(),
        }
        db.save_closedtickets(closed)

    reason_label, reason_emoji, reason_accent = TICKET_CLOSE_REASONS.get(
        reason, ("Resolved", E.check, 0x57F287)
    )

    log_ch = channel.guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if log_ch and info:
        status, resp = await api_send(log_ch.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": reason_accent,
                    "components": [
                        {
                            "type": 10,
                            "content": (
                                f"## {reason_emoji} Ticket Closed\n"
                                f"**Type** {info.get('type', '?').capitalize()}\n"
                                f"**Number** `#{number}`\n"
                                f"**Channel** `{channel.name}`\n"
                                f"**Opened by** <@{info.get('opener_id')}>\n"
                                f"**Closed by** {closed_by.mention}\n"
                                f"**Reason** {reason_label}\n"
                                f"**At** <t:{ts}:F>"
                            ),
                        }
                    ],
                }
            ],
        })
        # Send the transcript + reopen button.
        try:
            if number:
                view = ReopenView(number)
                bot = state.get_bot()
                if bot is not None:
                    bot.add_view(view)
                await log_ch.send(
                    content=f"Transcript — `{channel.name}`",
                    files=[html_file, txt_file],
                    view=view,
                )
        except Exception as e:
            log.error("Transcript send: %s", e)

    if interaction:
        await interaction.followup.send(f"{reason_emoji} Closing in 5 seconds…", ephemeral=True)
    else:
        try:
            await channel.send(f"{reason_emoji} Closing in 5 seconds…")
        except Exception:
            pass

    await asyncio.sleep(5)

    if str(channel.id) in tickets:
        del tickets[str(channel.id)]
        db.save_tickets(tickets)

    tlogs = db.ticketlogs()
    if str(channel.id) in tlogs:
        del tlogs[str(channel.id)]
        db.save_ticketlogs(tlogs)

    try:
        await channel.delete(reason=f"Closed by {closed_by} ({reason})")
    except Exception as e:
        log.error("Ticket delete: %s", e)


async def _reopen_ticket(interaction: discord.Interaction, number: int):
    closed = db.closedtickets()
    info = closed.get(str(number))
    if not info:
        await interaction.response.send_message(
            "This ticket can't be reopened.", ephemeral=True
        )
        return

    guild = interaction.guild
    opener_id = info.get("opener_id")
    opener = guild.get_member(opener_id) or await guild.fetch_member(opener_id)

    category = guild.get_channel(TICKET_CATEGORY_ID)
    overwrites = _build_overwrites(guild, opener)

    name = info.get("name") or f"{info.get('type', 'ticket')}-{number:04d}"
    channel = await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        topic=f"{info.get('type')} | {opener} ({opener.id}) | reopened",
    )

    tickets = db.tickets()
    tickets[str(channel.id)] = {
        "type":       info.get("type"),
        "opener_id":  opener.id,
        "number":     number,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name":       name,
    }
    db.save_tickets(tickets)

    del closed[str(number)]
    db.save_closedtickets(closed)

    ts = ts_now()
    await api_send(channel.id, {
        "flags": 32768,
        "components": [
            {
                "type": 17,
                "accent_color": 0x57F287,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"## 🔓 Ticket Reopened\n"
                            f"Ticket `#{number}` has been reopened.\n"
                            f"**Opened by** {opener.mention}\n**At** <t:{ts}:F>"
                        ),
                    }
                ],
            }
        ],
    })
    await channel.send(content=opener.mention, view=CloseTicketView())

    await interaction.response.send_message(
        f"{E.check} Ticket `#{number}` reopened in {channel.mention}.", ephemeral=True
    )


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

    overwrites = _build_overwrites(guild, member)

    number = _next_ticket_number()
    name   = f"{type_info['prefix']}-{number:04d}"
    channel = await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        topic=f"#{number} | {kind} | {member} ({member.id})",
    )

    tickets = db.tickets()
    tickets[str(channel.id)] = {
        "type":       kind,
        "opener_id":  member.id,
        "number":     number,
        "name":       name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_tickets(tickets)

    tlogs = db.ticketlogs()
    tlogs[str(channel.id)] = [
        "[TICKET OPENED]",
        f"Number  : #{number}",
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
            "content": f"**Ticket** `#{number}`\n**Opened by** {member.mention}\n**Opened at** <t:{ts}:F>",
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
                                f"**Number** `#{number}`\n"
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
        state.set_bot(bot)
        bot.add_view(CloseTicketView())
        # Re-register reopen buttons for closed tickets.
        for number in db.closedtickets():
            try:
                bot.add_view(ReopenView(int(number)))
            except ValueError:
                pass

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
