"""Image generation (rank cards) with Pillow.

Renders a polished, ocean-themed rank card. Fonts are resolved from matplotlib's
bundled DejaVu (always present when matplotlib is installed), falling back to
common system paths and finally Pillow's default bitmap font.
"""
from __future__ import annotations

import io
import logging
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

_CARD_W, _CARD_H = 1000, 300

# Ocean palette (dark navy → teal).
_BG_TOP = (16, 34, 61)
_BG_BOTTOM = (30, 96, 110)
_ACCENT = (94, 206, 255)
_GOLD = (255, 209, 102)
_TEXT = (235, 245, 255)
_MUTED = (150, 170, 195)
_BAR_BG = (20, 40, 70)

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _resolve_font_path() -> str:
    """Find a usable TTF font, preferring matplotlib's bundled DejaVu."""
    candidates = []
    try:
        import matplotlib
        mpl_dir = matplotlib.get_data_path()
        candidates += [
            str(mpl_dir / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"),
            str(mpl_dir / "fonts" / "ttf" / "DejaVuSans.ttf"),
        ]
    except Exception:
        pass
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            ImageFont.truetype(path, 10)
            return path
        except Exception:
            continue
    return ""


_FONT_PATH = _resolve_font_path()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    try:
        if _FONT_PATH:
            path = _FONT_PATH if bold else _FONT_PATH.replace("Bold", "")
            try:
                font = ImageFont.truetype(path, size)
            except Exception:
                font = ImageFont.truetype(_FONT_PATH, size)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _vertical_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (1, h), top)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((w, h))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


async def fetch_avatar_bytes(session, url: str) -> bytes | None:
    try:
        async with session.get(url) as r:
            if r.status == 200:
                return await r.read()
    except Exception as e:
        log.warning("avatar fetch failed: %s", e)
    return None


def _paste_avatar(card: Image.Image, avatar_bytes: bytes, box: tuple[int, int], size: int) -> None:
    """Paste a circular avatar into the card at the given top-left box."""
    try:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        return
    avatar = avatar.resize((size, size), Image.LANCZOS)
    # Circular mask.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    # Ring border.
    ring = Image.new("RGBA", (size + 12, size + 12), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, size + 11, size + 11), outline=_ACCENT + (255,), width=4)
    card.paste(ring, (box[0] - 6, box[1] - 6), ring)
    card.paste(avatar, box, mask)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Truncate with ellipsis to fit max_width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


async def generate_rank_card(
    session,
    *,
    avatar_url: str,
    username: str,
    level: int,
    xp: int,
    needed: int,
    rank: int,
    role_name: str | None = None,
    is_max: bool = False,
) -> bytes:
    """Render the rank card and return PNG bytes."""
    card = _vertical_gradient(_CARD_W, _CARD_H, _BG_TOP, _BG_BOTTOM)
    # Subtle radial glow behind the avatar.
    glow = Image.new("RGBA", (_CARD_W, _CARD_H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((30, 30, 270, 270), fill=(94, 206, 255, 26))
    card = Image.alpha_composite(card.convert("RGBA"), glow)

    draw = ImageDraw.Draw(card)

    # Avatar.
    avatar_bytes = await fetch_avatar_bytes(session, avatar_url)
    if avatar_bytes:
        _paste_avatar(card, avatar_bytes, (42, 48), 176)

    # Rank badge (right).
    badge_font = _font(54, bold=True)
    badge_text = f"#{rank}"
    bw = draw.textlength(badge_text, font=badge_font)
    draw.rounded_rectangle(
        (_CARD_W - 60 - bw - 40, 30, _CARD_W - 30, 30 + 84), radius=20, fill=(255, 255, 255, 24)
    )
    draw.text((_CARD_W - 60 - bw - 10, 36), badge_text, font=badge_font, fill=_GOLD)

    # Username.
    name_font = _font(44, bold=True)
    username = _fit_text(draw, username, name_font, 600)
    draw.text((248, 58), username, font=name_font, fill=_TEXT)

    # Level + role line.
    sub_font = _font(26)
    level_text = f"Level {level}"
    if role_name:
        level_text += f"  ·  {role_name}"
    draw.text((250, 122), _fit_text(draw, level_text, sub_font, 660), font=sub_font, fill=_MUTED)

    # XP progress bar.
    bar_x, bar_y, bar_w, bar_h = 250, 186, 660, 34
    if is_max:
        pct = 1.0
    else:
        pct = min(xp / needed, 1.0) if needed else 0.0
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=17, fill=_BAR_BG
    )
    if pct > 0:
        fill_w = max(int(bar_w * pct), 30)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=17, fill=_ACCENT
        )
    # XP text inside the bar.
    xp_font = _font(22, bold=True)
    xp_text = f"{xp:,} XP · MAX LEVEL" if is_max else f"{xp:,} / {needed:,} XP"
    draw.text((bar_x + 20, bar_y + 5), xp_text, font=xp_font, fill=(10, 20, 40))

    # Percentage (right of bar).
    pct_text = "MAX" if is_max else f"{int(pct * 100)}%"
    draw.text((_CARD_W - 56 - draw.textlength(pct_text, font=xp_font), bar_y + 5),
              pct_text, font=xp_font, fill=_GOLD)

    # Footer watermark.
    foot_font = _font(18)
    draw.text((42, _CARD_H - 40), "MyPineapple", font=foot_font, fill=(120, 150, 180))
    draw.text((_CARD_W - 42 - draw.textlength("🍍 rank card", font=foot_font), _CARD_H - 40),
              "🍍 rank card", font=foot_font, fill=(120, 150, 180))

    buf = io.BytesIO()
    card.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
