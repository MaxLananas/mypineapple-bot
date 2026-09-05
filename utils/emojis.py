"""Emojis centralisés pour MyPineapple — thème océan / île / tropical.

Unicode (rendus partout, sans config serveur). Utilise-les dans tout le bot
pour un style cohérent : `from utils.emojis import E` puis `E.arrow`, etc.
"""
from __future__ import annotations


class _E:
    # ── Marque / thème ──────────────────────────────────────────
    pineapple = "🍍"
    wave      = "🌊"
    island    = "🏝️"
    palm      = "🌴"
    sun       = "☀️"
    shell     = "🐚"
    coral     = "🪸"
    starfish  = "⭐"
    lighthouse = "🗼"

    # ── Flèches / navigation ─────────────────────────────────────
    arrow_left   = "⬅️"
    arrow_right  = "➡️"
    arrow_up     = "⬆️"
    arrow_down   = "⬇️"
    back         = "◀️"
    forward      = "▶️"
    double_left  = "⏮️"
    double_right = "⏭️"
    refresh      = "🔄"
    up_down      = "↕️"

    # ── Points / statut ─────────────────────────────────────────
    dot_green  = "🟢"
    dot_yellow = "🟡"
    dot_red    = "🔴"
    dot_blue   = "🔵"
    dot_orange = "🟠"
    dot_white  = "⚪"
    dot_black  = "⚫"
    check      = "✅"
    cross      = "❌"
    warning    = "⚠️"
    info       = "ℹ️"
    question   = "❓"
    exclamation = "❗"
    lock       = "🔒"
    unlock     = "🔓"

    # ── Médaille / récompense ───────────────────────────────────
    gold   = "🥇"
    silver = "🥈"
    bronze = "🥉"
    trophy = "🏆"
    crown  = "👑"
    medal  = "🎖️"
    gift   = "🎁"
    gem    = "💎"
    star   = "⭐"
    sparkle = "✨"

    # ── Animaux marins (palier) ─────────────────────────────────
    crab   = "🦀"
    fish   = "🐟"
    jelly  = "🪼"
    dolphin = "🐬"
    squid  = "🦑"
    octopus = "🐙"
    mermaid = "🧜"
    whale  = "🐋"
    shark  = "🦈"
    turtle = "🐢"

    # ── Outils / actions ────────────────────────────────────────
    hammer  = "🔨"
    wrench  = "🔧"
    gear    = "⚙️"
    rocket  = "🚀"
    fire    = "🔥"
    heart   = "❤️"
    thumbsup = "👍"
    thumbsdown = "👎"
    pin     = "📌"
    calendar = "📅"
    clock   = "🕐"
    hourglass = "⏳"
    inbox   = "📥"
    outbox  = "📤"
    folder  = "📁"
    file    = "📄"
    link    = "🔗"
    download = "⬇️"
    search  = "🔍"
    eye     = "👁️"
    mic     = "🎙️"
    speaker = "🔊"
    mute    = "🔇"

    # ── Divers / fun ────────────────────────────────────────────
    dice    = "🎲"
    coin    = "🪙"
    eight   = "🎱"
    party   = "🎉"
    confetti = "🎊"
    thought = "💭"
    book    = "📚"
    pencil  = "✏️"
    paint   = "🎨"
    chart   = "📊"
    bar_chart = "📊"
    line_chart = "📈"
    bell    = "🔔"
    tag     = "🏷️"
    shield  = "🛡️"
    key     = "🔑"
    bug     = "🐛"
    money   = "💰"
    banknote = "💶"


E = _E()


def all_emojis() -> list[str]:
    """Liste des emojis uniques disponibles (utile pour la doc / help)."""
    seen, out = set(), []
    for name in dir(E):
        if name.startswith("_"):
            continue
        v = getattr(E, name)
        if isinstance(v, str) and v not in seen:
            seen.add(v)
            out.append(v)
    return out
