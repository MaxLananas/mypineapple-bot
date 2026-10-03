"""Ocean-themed rank card generator (Pillow only — no numpy/matplotlib).

The card is rendered entirely with Pillow for a tiny memory/CPU footprint
(important on a 256 MB host). Real colour emojis are composited from Twemoji
PNGs fetched at runtime and cached; when the fetch fails the card still
renders cleanly (the emoji is simply omitted) — never a crash.

Fonts are bundled under ``assets/fonts`` (committed to the repo) so rendering
is identical on any host, regardless of installed system fonts.
"""
from __future__ import annotations

import io
import logging
import math
import os
from collections import OrderedDict

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

# Short timeout for image/emoji fetches so a slow CDN never hangs a command.
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=8)

# ── Geometry ─────────────────────────────────────────────────────────────────
CARD_W, CARD_H = 1200, 400

# ── Palette (ocean) ──────────────────────────────────────────────────────────
_BG_TOP    = (8, 24, 46)
_BG_BOTTOM = (18, 74, 100)
_GLOW      = (72, 190, 240)
_ACCENT    = (94, 206, 255)      # cyan
_ACCENT2   = (255, 209, 102)     # gold
_TEXT      = (238, 247, 255)
_MUTED     = (150, 176, 199)
_BAR_BG    = (12, 38, 62)

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts"
)
_FONT_BOLD = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
_FONT_REG = os.path.join(_FONT_DIR, "DejaVuSans.ttf")

_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    path = _FONT_BOLD if bold else _FONT_REG
    try:
        font = ImageFont.truetype(path, size)
    except Exception:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


# ── Emoji helpers (Twemoji) ──────────────────────────────────────────────────
_TWEMOJI_BASE = [
    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/{cp}.png",
    "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{cp}.png",
]
_emoji_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
_EMOJI_CACHE_MAX = 64


def _codepoint(emoji: str) -> str:
    """Convert an emoji to its Twemoji codepoint (variation selectors/ZWJ stripped)."""
    return "-".join(f"{ord(c):x}" for c in emoji if c not in "\ufe0f\u200d")


async def _fetch_emoji(session, emoji: str) -> Image.Image | None:
    """Download + cache a Twemoji PNG for ``emoji``. Returns None on failure."""
    if not emoji:
        return None
    if emoji in _emoji_cache:
        _emoji_cache.move_to_end(emoji)
        return _emoji_cache[emoji]

    cp = _codepoint(emoji)
    for base in _TWEMOJI_BASE:
        try:
            async with session.get(base.format(cp=cp), timeout=_FETCH_TIMEOUT) as r:
                if r.status != 200:
                    continue
                img = Image.open(io.BytesIO(await r.read())).convert("RGBA")
                _emoji_cache[emoji] = img
                while len(_emoji_cache) > _EMOJI_CACHE_MAX:
                    _emoji_cache.popitem(last=False)
                return img
        except Exception:
            continue
    return None


def _leading_emoji(text: str | None) -> str:
    """Extract the leading emoji (incl. variation selector / ZWJ sequences)."""
    if not text:
        return ""
    out = text[0]
    i = 1
    while i < len(text):
        c = text[i]
        if c in "\ufe0f\u200d":
            out += c
            i += 1
        elif text[i - 1] == "\u200d":
            out += c
            i += 1
        else:
            break
    return out if ord(out[0]) > 0x2000 else ""


# ── Drawing primitives ───────────────────────────────────────────────────────

def _vgradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize((w, h))


def _hgradient(w: int, h: int, left: tuple, right: tuple) -> Image.Image:
    strip = Image.new("RGB", (w, 1))
    for x in range(w):
        t = x / max(w - 1, 1)
        strip.putpixel((x, 0), tuple(int(left[i] + (right[i] - left[i]) * t) for i in range(3)))
    return strip.resize((w, h))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    return mask


def _paste_rounded(card: Image.Image, img: Image.Image, box: tuple[int, int], radius: int) -> None:
    card.paste(img, box, _rounded_mask(img.size, radius))


def _paste_circle(card: Image.Image, img: Image.Image, center: tuple[int, int], radius: int) -> None:
    size = radius * 2
    img = img.resize((size, size), Image.LANCZOS)
    card.paste(img, (center[0] - radius, center[1] - radius), _circle_mask(size))


def _paste_emoji(card: Image.Image, img: Image.Image, box: tuple[int, int], size: int) -> None:
    img = img.resize((size, size), Image.LANCZOS)
    card.paste(img, box, img)  # RGBA image as its own mask


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _draw_waves(card: Image.Image, base_y: int, amp: int, wavelength: int, color: tuple, alpha: int) -> None:
    layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    points = [
        (x, base_y + int(amp * math.sin((x / wavelength) * 2 * math.pi)))
        for x in range(0, CARD_W + 1)
    ]
    points += [(CARD_W, CARD_H), (0, CARD_H)]
    d.polygon(points, fill=color + (alpha,))
    card.alpha_composite(layer)


def _draw_bubbles(card: Image.Image) -> None:
    d = ImageDraw.Draw(card)
    for (cx, cy, r) in [(210, 90, 10), (260, 60, 6), (940, 120, 12), (990, 80, 7), (1040, 160, 5)]:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 40), width=2)


async def _fetch_bytes(session, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=_FETCH_TIMEOUT) as r:
            if r.status == 200:
                return await r.read()
    except Exception as e:
        log.warning("image fetch failed: %s", e)
    return None


# ── Main card ────────────────────────────────────────────────────────────────

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
    card = _vgradient(CARD_W, CARD_H, _BG_TOP, _BG_BOTTOM).convert("RGBA")

    # Sunlight glow through water (top-right).
    glow = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((CARD_W - 320, -180, CARD_W + 220, 360), fill=_GLOW + (36,))
    card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

    # Decorative waves + bubbles.
    _draw_waves(card, CARD_H - 60, 14, 260, (52, 140, 180), 70)
    _draw_waves(card, CARD_H - 40, 10, 180, (34, 120, 160), 90)
    _draw_bubbles(card)

    draw = ImageDraw.Draw(card)

    # ── Avatar (circular, ring + soft shadow) ────────────────────────────────
    avatar_cx, avatar_cy, avatar_r = 130, CARD_H // 2, 104
    ring_size = avatar_r * 2 + 16
    ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((3, 3, ring_size - 3, ring_size - 3), outline=(0, 0, 0, 60), width=10)  # shadow
    rd.ellipse((0, 0, ring_size, ring_size), outline=_ACCENT + (255,), width=8)         # accent ring
    card.paste(ring, (avatar_cx - ring_size // 2, avatar_cy - ring_size // 2), ring)

    avatar_bytes = await _fetch_bytes(session, avatar_url)
    if avatar_bytes:
        try:
            _paste_circle(card, Image.open(io.BytesIO(avatar_bytes)).convert("RGBA"),
                          (avatar_cx, avatar_cy), avatar_r)
        except Exception as e:
            log.warning("avatar paste: %s", e)

    # ── Rank badge (top-right) ───────────────────────────────────────────────
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank)
    badge_text = f"RANK #{rank}"
    badge_font = _font(30, bold=True)
    bw = int(draw.textlength(badge_text, font=badge_font))
    bx0, by0 = CARD_W - 40 - bw - (56 if medal else 48), 32
    bx1, by1 = CARD_W - 32, 32 + 62
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=18, fill=(255, 255, 255, 22))
    draw.text((bx0 + 22, by0 + 13), badge_text, font=badge_font, fill=_ACCENT2)
    if medal:
        med_img = await _fetch_emoji(session, medal)
        if med_img:
            _paste_emoji(card, med_img, (bx1 - 56, by0 + 9), 44)

    # ── Username + subtitle ──────────────────────────────────────────────────
    name_font = _font(52, bold=True)
    username = _fit_text(draw, username, name_font, 560)
    tx = avatar_cx + avatar_r + 40
    draw.text((tx, 96), username, font=name_font, fill=_TEXT)

    sub_font = _font(27)
    sub_parts = [f"Level {level}"]
    if role_name:
        sub_parts.append(role_name)
    draw.text((tx, 158), _fit_text(draw, "  ·  ".join(sub_parts), sub_font, 620), font=sub_font, fill=_MUTED)

    # ── Level-role emoji (large decorative, right side) ──────────────────────
    role_emoji = _leading_emoji(role_name) if role_name else ""
    if role_emoji:
        emoji_img = await _fetch_emoji(session, role_emoji)
        if emoji_img:
            _paste_emoji(card, emoji_img, (CARD_W - 210, 150), 120)

    # ── XP progress bar ──────────────────────────────────────────────────────
    bar_x, bar_y, bar_w, bar_h = tx, 240, 560, 38
    if is_max:
        pct, fill_w = 1.0, bar_w
    else:
        pct = min(xp / needed, 1.0) if needed else 0.0
        fill_w = max(int(bar_w * pct), 20) if pct > 0 else 0

    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=19, fill=_BAR_BG)
    if fill_w:
        _paste_rounded(card, _hgradient(fill_w, bar_h, _ACCENT, _ACCENT2).convert("RGBA"),
                       (bar_x, bar_y), 19)

    xp_font = _font(22, bold=True)
    xp_label = f"{xp:,} XP  ·  MAX LEVEL" if is_max else f"{xp:,} / {needed:,} XP"
    draw.text((bar_x + 22, bar_y + 7), xp_label, font=xp_font, fill=(10, 22, 40))

    pct_text = "MAX" if is_max else f"{int(pct * 100)}%"
    pct_w = int(draw.textlength(pct_text, font=xp_font))
    draw.text((bar_x + bar_w - pct_w - 22, bar_y + 7), pct_text, font=xp_font, fill=(255, 255, 255, 220))

    # ── Footer watermark ─────────────────────────────────────────────────────
    foot_font = _font(18)
    pine = await _fetch_emoji(session, "🍍")
    if pine:
        _paste_emoji(card, pine, (42, CARD_H - 42), 20)
        draw.text((70, CARD_H - 40), "MyPineapple", font=foot_font, fill=(130, 158, 180))
    else:
        draw.text((42, CARD_H - 40), "MyPineapple", font=foot_font, fill=(130, 158, 180))

    right = f"{xp:,} XP · Lv {level}"
    rw = int(draw.textlength(right, font=foot_font))
    draw.text((CARD_W - 42 - rw, CARD_H - 40), right, font=foot_font, fill=(130, 158, 180))

    buf = io.BytesIO()
    card.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
