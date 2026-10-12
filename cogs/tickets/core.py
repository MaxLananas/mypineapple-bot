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
from utils import ui
from config import (
    LOGO_URL,
    TICKET_CATEGORY_ID, TICKET_LOG_CHANNEL_ID, SUPPORT_ROLE_ID,
)

from . import state
from .constants import (
    TICKET_PANEL_LINES,
    DEFAULT_LANG, LANGS, TICKET_BUTTONS, TICKET_CLOSE_REASONS, TICKET_TYPES,
    _build_overwrites, _is_valid_url, _next_ticket_number, build_ticket_intro,
)
from .transcript import _history_to_logs, _transcript_html, _transcript_txt
from .views import CloseTicketView, ReopenView, TicketLangView

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

    if not info:
        # Sécurité : ne JAMAIS supprimer un salon qui n'est pas un ticket suivi
        # (ex. bouton resté dans un vieux salon, base restaurée…).
        log.warning("Close requested on untracked channel %s (%s)", channel.name, channel.id)
        if interaction:
            await ui.send(interaction, ui.info_card(
                "Not a tracked ticket", "This channel isn't one of my tickets."
            ), ephemeral=True)
        return

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
        closing = ui.Card("## 🔒 Ticket closing", accent=reason_accent)
        closing.text(f"Reason: **{reason_label}**\nThis channel disappears in **5 seconds**.")
        closing.footer("A transcript is being sent to the log channel")
        await ui.send(interaction, closing, ephemeral=True)
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
        await ui.send(interaction, ui.warn_card(
            "Cannot reopen", "I have no record of that ticket number."
        ), ephemeral=True)
        return

    # ACK immédiat : créer le salon + envoyer plusieurs messages dépasse
    # facilement les 3 s de la fenêtre d'interaction.
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    opener_id = info.get("opener_id")
    opener = guild.get_member(opener_id)
    if opener is None:
        try:
            opener = await guild.fetch_member(opener_id)
        except discord.HTTPException:
            opener = None
    if opener is None:
        await ui.send(interaction, ui.warn_card(
            "Member left",
            "The member who opened this ticket is no longer on the server.",
        ), ephemeral=True)
        return

    category = guild.get_channel(TICKET_CATEGORY_ID)
    overwrites = _build_overwrites(guild, opener)

    name = info.get("name") or f"{info.get('type', 'ticket')}-{number:04d}"
    try:
        channel = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            topic=f"{info.get('type')} | {opener} ({opener.id}) | reopened",
        )
    except discord.HTTPException as e:
        log.error("reopen create_text_channel: %s", e)
        await ui.send(interaction, ui.error_card(
            "Reopen failed",
            f"Discord refused the request (`{getattr(e, 'status', 'error')}`).",
        ), ephemeral=True)
        return

    ts_open = ts_now()
    lang = info.get("lang") if info.get("lang") in LANGS else DEFAULT_LANG
    tickets = db.tickets()
    tickets[str(channel.id)] = {
        "type":       info.get("type"),
        "opener_id":  opener.id,
        "number":     number,
        "lang":       lang,
        "opened_ts":  ts_open,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name":       name,
    }
    db.save_tickets(tickets)

    del closed[str(number)]
    db.save_closedtickets(closed)

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
                            f"**Opened by** {opener.mention}\n**At** <t:{ts_open}:F>"
                        ),
                    }
                ],
            }
        ],
    })
    # Le message-guide est renvoyé en haut du salon (avec son bouton de langue).
    await api_send(channel.id, {
        "flags": 32768,
        "components": build_ticket_intro(
            info.get("type") or "question", lang, number, opener.id, ts_open
        ),
    })
    await channel.send(content=opener.mention, view=CloseTicketView())

    await ui.send(interaction, ui.ok_card(
        f"Ticket #{number} reopened",
        f"{channel.mention} is live again — the guide is already posted inside.",
    ), ephemeral=True)


async def _create_ticket(
    interaction: discord.Interaction,
    kind:        str,
    *,
    lang:        str = DEFAULT_LANG,
) -> discord.TextChannel:
    """Crée le salon du ticket et y poste le message-guide bilingue.

    Plus de formulaire (modal) : le salon s'ouvre directement, le bot explique
    en haut ce qu'il faut indiquer, et l'utilisateur écrit sa demande dessous.
    """
    guild        = interaction.guild
    member       = interaction.user
    category     = guild.get_channel(TICKET_CATEGORY_ID)
    support_role = guild.get_role(SUPPORT_ROLE_ID)
    type_info    = TICKET_TYPES[kind]
    ts           = ts_now()

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
        "lang":       lang if lang in LANGS else DEFAULT_LANG,
        "opened_ts":  ts,
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

    ticket_info = tickets[str(channel.id)]
    await api_send(channel.id, {
        "flags": 32768,
        "components": build_ticket_intro(
            kind,
            ticket_info["lang"],
            number,
            member.id,
            ts,
        ),
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


async def _open_ticket(interaction: discord.Interaction, kind: str) -> None:
    """Clic sur un bouton du panel → le salon du ticket est créé directement.

    Remplace l'ancien flux « modal » : plus de formulaire à remplir, le bot
    poste un message-guide (EN par défaut, bouton FR) et l'utilisateur écrit
    sa demande dans le salon.
    """
    uid = interaction.user.id

    # Un seul ticket ouvert par type et par membre (comme avant).
    for info in db.tickets().values():
        if info.get("opener_id") == uid and info.get("type") == kind:
            await ui.send(interaction, ui.warn_card(
                "Ticket already open",
                "You already have an open ticket of this type. "
                "Close it before opening a new one.",
            ), ephemeral=True)
            return

    # Créer le salon + y poster plusieurs messages dépasse les 3 s : on accuse
    # réception tout de suite, puis on répond en followup.
    await interaction.response.defer(ephemeral=True)

    label = TICKET_TYPES.get(kind, {}).get("label", kind.capitalize())
    try:
        channel = await _create_ticket(interaction, kind)
    except discord.HTTPException as e:
        log.error("open %s ticket: %s", kind, e)
        await ui.send(interaction, ui.error_card(
            f"Couldn't create the {label} ticket",
            f"Discord answered `{getattr(e, 'status', 'error')}`. "
            "Check my **Manage Channels** permission.",
        ), ephemeral=True)
        return

    await ui.send(interaction, ui.ok_card(
        f"{label} ticket created",
        f"Head to {channel.mention} — your ticket is open, our team will answer there.",
    ), ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        state.set_bot(bot)
        bot.add_view(CloseTicketView())
        bot.add_view(TicketLangView())
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
        if cid in TICKET_BUTTONS:
            try:
                await _open_ticket(interaction, TICKET_BUTTONS[cid])
            except Exception as e:
                # Dernier filet : une erreur ici produisait un
                # « Unhandled event error in 'on_interaction' » et laissait
                # l'utilisateur devant « Interaction failed » sans explication.
                log.exception("ticket button %s: %s", cid, e)
                try:
                    await ui.error(interaction, "Something went wrong on my side. "
                                                "Please try again in a moment.")
                except Exception:
                    pass

    @app_commands.command(name="ticket-panel", description="Send the ticket panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Panel en carte du design system : comment ça marche, les catégories,
        # puis les boutons. Le guide de chaque salon est bilingue (bouton FR).
        panel = ui.Card("", accent=ui.ACCENT_BRAND, thumbnail=LOGO_URL)
        panel.header(
            "# 🌊 MyPineapple Support\n"
            "Pick a category below — a **private channel** opens right away, "
            "with a step-by-step guide inside."
        )
        panel.divider()
        panel.text("**How it works**\n"
                   "`1` Click a category button below\n"
                   "`2` A private channel opens with you and the team\n"
                   "`3` The guide tells you exactly what to include")
        panel.divider(spacing=1)
        panel.text("**Categories**\n" + "\n".join(
            f"{info['emoji']} **{info['label']}** — {TICKET_PANEL_LINES.get(kind, '')}"
            for kind, info in TICKET_TYPES.items()
        ))
        panel.divider()
        buttons = []
        for custom_id, kind in TICKET_BUTTONS.items():
            info = TICKET_TYPES[kind]
            buttons.append(discord.ui.Button(
                label=info["label"], emoji=info["emoji"],
                style=discord.ButtonStyle.primary if info.get("style") == 1
                else discord.ButtonStyle.secondary,
                custom_id=custom_id,
            ))
        for i in range(0, len(buttons), 5):
            panel.row(*buttons[i:i + 5])
        panel.divider(spacing=1).footer(
            "Kicked off by MyPineapple · answers in the ticket, not here 🍍"
        )

        status, resp = await api_send(interaction.channel.id, panel.payload())
        if status in (200, 201):
            await ui.send(interaction, ui.ok_card(
                "Ticket panel posted",
                "Previews & buttons are live — click one to test the flow.",
            ), ephemeral=True)
        else:
            await ui.send(interaction, ui.error_card(
                "Panel not posted",
                f"Discord answered `{status}`. Check my **Send Messages** permission here.",
            ), ephemeral=True)

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
            await ui.send(interaction, ui.info_card(
                "Not a tracked ticket", "This channel isn't one of my tickets."
            ), ephemeral=True)
            return

        if info.get("type") != "commission":
            await ui.send(interaction, ui.warn_card(
                "Wrong ticket type", "This command only works inside a **Commission** ticket."
            ), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        delivery_message = delivery_message[:3500]  # limite des blocs de texte

        opener_id = info.get("opener_id")
        ts        = ts_now()
        guild     = interaction.guild
        opener    = guild.get_member(opener_id)
        if opener is None:
            try:
                opener = await guild.fetch_member(opener_id)
            except discord.HTTPException:
                opener = None  # a quitté le serveur → on continue sans DM
        opener_mention = opener.mention if opener else "the client"

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
                                    f"Your commission has been completed, {opener_mention}."
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

        await ui.send(interaction, ui.ok_card(
            "Delivery sent",
            "The client got the message and the ticket closes in **10 seconds**.",
        ), ephemeral=True)
        await asyncio.sleep(10)
        await _do_close_ticket(channel, interaction.user)
