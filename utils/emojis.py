"""Emojis centralisés pour MyPineapple — thème océan / île / tropical.

Unicode (rendus partout, sans config serveur). Utilise-les dans tout le bot
pour un style cohérent : `from utils.emojis import E` puis `E.arrow`, etc.
"""
from __future__ import annotations

import discord


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


class _Custom:
    """Emojis custom du serveur (IDs fixes, uploadés par l'admin).

    Contrairement à ``E`` (unicode), ces emojis ne s'affichent que si le bot les
    connaît : ils sont donc référencés en dur sous la forme ``<:nom:id>``.
    Utilisation : ``from utils.emojis import C`` puis ``C.modrinth``.
    """
    discord   = "<:emoji_44:1555976835752272052>"
    instagram = "<:DPJqh3xa92JHF6RnNAqOTLyL735RtVap:1556012609499566191>"
    tiktok    = "<:C6RrzAIWx4R04ZRaj4SFouEnubhfT4eP:1556013527070941234>"
    youtube   = "<:emoji_40:1555975578170032158>"
    website   = "<:emoji_41:1555975607760982036>"
    modrinth  = "<:emoji_42:1555975629873348659>"
    github    = "<:emoji_43:1555975649103970304>"


C = _Custom()


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


def resolve(guild, key: str, fallback: str) -> str:
    """Retourne l'emoji custom du serveur s'il existe (nommé `mp_<key>`),
    sinon le fallback unicode. Permet d'utiliser des emojis de serveur sans
    coder d'IDs en dur : il suffit de nommer les emojis `mp_arrow_left`, etc."""
    if guild is None:
        return fallback
    emoji = discord.utils.get(guild.emojis, name=f"mp_{key}")
    return str(emoji) if emoji else fallback
