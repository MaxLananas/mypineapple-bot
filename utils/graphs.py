"""7-day XP bar chart rendered with Pillow (no numpy/matplotlib).

Matplotlib pulls in numpy (~100 MB+ of resident memory) which is risky on a
256 MB host; this module draws an equally polished, theme-matched chart with
pure Pillow and the bundled DejaVu fonts.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from utils.images import _font, _vgradient, _rounded_mask

log = logging.getLogger(__name__)

W, H = 1000, 300
_PALETTE = [
    "#5ECFFF", "#FFD166", "#8DA1AD", "#B8A0D0",
    "#C8F0C8", "#FFB3BA", "#A0D8EF",
]


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def generate_xp_graph(*, username: str, daily_xp: dict[str, int], days: int = 7) -> bytes:
    """Render a 7-day XP bar chart and return PNG bytes."""
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=d) for d in range(days - 1, -1, -1)]
    values = [int(daily_xp.get(d.strftime("%Y-%m-%d"), 0)) for d in dates]
    max_v = max(values) if any(values) else 1

    # Background (ocean gradient).
    img = _vgradient(W, H, (15, 23, 42), (18, 54, 78)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Title.
    title_font = _font(26, bold=True)
    title = f"XP — {username} (last {days} days)"
    draw.text((32, 24), title, font=title_font, fill=(226, 232, 240))

    # Chart area.
    left, top, right, bottom = 60, 90, W - 40, H - 40
    plot_h = bottom - top
    draw.line((left, bottom, right, bottom), fill=(30, 41, 59), width=2)

    # Bars.
    n = len(values)
    slot = (right - left) / n
    bar_w = int(slot * 0.55)
    for i, v in enumerate(values):
        color = _hex(_PALETTE[i % len(_PALETTE)])
        bh = int((v / max_v) * (plot_h - 34)) if v else 3
        x0 = int(left + slot * i + (slot - bar_w) / 2)
        y0 = bottom - bh
        x1, y1 = x0 + bar_w, bottom
        radius = min(12, bar_w // 2, bh // 2)
        if radius <= 0:
            draw.rectangle((x0, y0, x1, y1), fill=color)
        else:
            # Rounded-top bar (rounded rectangle, then square off the bottom).
            draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=color)
            draw.rectangle((x0, y0 + radius, x1, y1), fill=color)

        # Day label.
        day_font = _font(15)
        lbl = dates[i].strftime("%a")
        lw = draw.textlength(lbl, font=day_font)
        draw.text((x0 + (bar_w - lw) / 2, bottom + 8), lbl, font=day_font, fill=(100, 116, 139))

        # Value label above bar.
        if v:
            val_font = _font(15, bold=True)
            vtxt = str(v)
            vw = draw.textlength(vtxt, font=val_font)
            draw.text((x0 + (bar_w - vw) / 2, y0 - 22), vtxt, font=val_font, fill=(203, 213, 225))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
