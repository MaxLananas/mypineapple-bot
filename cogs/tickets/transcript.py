from __future__ import annotations

import html
import logging

import discord

from .constants import _is_image_url

log = logging.getLogger(__name__)


def _transcript_txt(logs: list[str]) -> str:
    return "\n".join(logs)


async def _history_to_logs(channel: discord.TextChannel, info: dict) -> list[str]:
    """Rebuild the transcript from the channel history (source of truth)."""
    lines = [
        "[TICKET OPENED]",
        f"Number  : #{info.get('number', '?')}",
        f"Type    : {info.get('type', '?')}",
        f"Channel : {channel.name} ({channel.id})",
        "─" * 48,
    ]
    try:
        async for msg in channel.history(limit=1000, oldest_first=True):
            if msg.author.bot and not msg.content and not msg.attachments:
                continue
            ts = msg.created_at.strftime("%H:%M:%S")
            line = f"[{ts}] {msg.author} ({msg.author.id}): {msg.content}"
            if msg.attachments:
                line += " | attachments: " + ", ".join(a.url for a in msg.attachments)
            lines.append(line)
    except Exception as e:
        log.error("_history_to_logs: %s", e)
    return lines


def _transcript_html(logs: list[str], title: str) -> str:
    """Readable HTML transcript with embedded images."""
    esc = html.escape
    body_parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;"
        "padding:24px;max-width:800px;margin:auto}"
        "h1{color:#38bdf8}.line{padding:6px 0;border-bottom:1px solid #1e293b;"
        "font-family:monospace;white-space:pre-wrap}"
        "img{max-width:100%;border-radius:8px;margin:8px 0}</style></head><body>",
        f"<h1>{esc(title)}</h1>",
    ]
    for line in logs:
        line_esc = esc(line)
        # Detect image URLs and embed them.
        for token in line.split():
            if _is_image_url(token):
                line_esc = line_esc.replace(
                    esc(token), f'<br><img src="{esc(token)}" alt="image"/>'
                )
        body_parts.append(f"<div class='line'>{line_esc}</div>")
    body_parts.append("</body></html>")
    return "\n".join(body_parts)
