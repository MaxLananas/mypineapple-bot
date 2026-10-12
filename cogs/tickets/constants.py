from __future__ import annotations

import discord

import utils.db as db
from utils.emojis import E
from utils import ui
from config import LOGO_URL, SUPPORT_ROLE_ID


def _is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


TICKET_CLOSE_REASONS = {
    "resolved":  ("Resolved",  E.check,     0x57F287),
    "abandoned": ("Abandoned", E.hourglass, 0xFEE75C),
    "duplicate": ("Duplicate", E.file,      0xA8D8EA),
}


def _next_ticket_number() -> int:
    cfg = db.config()
    n = int(cfg.get("ticket_counter", 0)) + 1
    cfg["ticket_counter"] = n
    db.save_config(cfg)
    return n


TICKET_TYPES = {
    "commission": {
        "label":  "Commission",
        "emoji":  "🎨",
        "style":  1,
        "accent": ui.TICKET_ACCENTS["commission"],
        "prefix": "commission",
        # Texte bilingue : le salon s'ouvre en anglais, le bouton du salon
        # bascule header + guide + méta en français (et inversement).
        "header": {
            "en": "# 🌊 MyPineapple Commissions\n## COMMISSION REQUEST",
            "fr": "# 🌊 MyPineapple Commissions\n## DEMANDE DE COMMANDE",
        },
        "guide": {
            "en": (
                "**Write your request below** 👇\n"
                "• **What you need** — build, plugin, mod, terraforming…\n"
                "• **Full description** — style, size, deadline, references\n"
                "• **Budget** — or ask us for a quote\n\n"
                "You can attach screenshots and reference images directly in this channel. 🍍"
            ),
            "fr": (
                "**Écris ta demande ci-dessous** 👇\n"
                "• **Ce dont tu as besoin** — build, plugin, mod, terraforming…\n"
                "• **Description complète** — style, taille, délai, références\n"
                "• **Budget** — ou demande-nous un devis\n\n"
                "Tu peux joindre captures d'écran et images de référence directement dans ce salon. 🍍"
            ),
        },
        "color":  discord.ButtonStyle.primary,
    },
    "recruitment": {
        "label":  "Recruitment",
        "emoji":  "🏗️",
        "style":  2,
        "accent": ui.TICKET_ACCENTS["recruitment"],
        "prefix": "recruit",
        "header": {
            "en": "# 🌊 MyPineapple Builders\n## BUILDER RECRUITMENT",
            "fr": "# 🌊 MyPineapple Builders\n## RECRUTEMENT DE BUILDER",
        },
        "guide": {
            "en": (
                "**Apply below** 👇\n"
                "• **Minecraft username / pseudo**\n"
                "• **Age & country / timezone**\n"
                "• **Experience** — how long, which servers/projects/teams, which styles (medieval, modern, terraforming…)\n"
                "• **Portfolio** — Imgur, Planet Minecraft, Instagram, YouTube, Drive…\n"
                "• **Availability & motivation** — hours per week, why you want to join"
            ),
            "fr": (
                "**Postule ci-dessous** 👇\n"
                "• **Pseudo Minecraft**\n"
                "• **Âge & pays / fuseau horaire**\n"
                "• **Expérience** — depuis combien de temps, quels serveurs/projets/équipes, quels styles (médiéval, moderne, terraforming…)\n"
                "• **Portfolio** — Imgur, Planet Minecraft, Instagram, YouTube, Drive…\n"
                "• **Disponibilité & motivation** — heures par semaine, pourquoi tu veux nous rejoindre"
            ),
        },
        "color":  discord.ButtonStyle.secondary,
    },
    "bug": {
        "label":  "Bug Report",
        "emoji":  "🐛",
        "style":  2,
        "accent": ui.TICKET_ACCENTS["bug"],
        "prefix": "bug",
        "header": {
            "en": "# 🌊 MyPineapple Bug Reports\n## BUG REPORT",
            "fr": "# 🌊 MyPineapple Bug Reports\n## RAPPORT DE BUG",
        },
        "guide": {
            "en": (
                "**Describe the bug below** 👇\n"
                "• **What is broken** — one sentence\n"
                "• **Steps to reproduce** — 1. 2. 3.\n"
                "• **Expected result** vs **actual result**\n"
                "• **Screenshot or video link** (optional)\n\n"
                "-# Adding the server/version helps us a lot."
            ),
            "fr": (
                "**Décris le bug ci-dessous** 👇\n"
                "• **Ce qui ne marche pas** — en une phrase\n"
                "• **Étapes pour reproduire** — 1. 2. 3.\n"
                "• **Résultat attendu** vs **résultat obtenu**\n"
                "• **Lien capture ou vidéo** (optionnel)\n\n"
                "-# Préciser le serveur/la version nous aide beaucoup."
            ),
        },
        "color":  discord.ButtonStyle.secondary,
    },
    "partnership": {
        "label":  "Partnership",
        "emoji":  "🤝",
        "style":  2,
        "accent": ui.TICKET_ACCENTS["partnership"],
        "prefix": "partner",
        "header": {
            "en": "# 🌊 MyPineapple Partnerships\n## PARTNERSHIP REQUEST",
            "fr": "# 🌊 MyPineapple Partnerships\n## DEMANDE DE PARTENARIAT",
        },
        "guide": {
            "en": (
                "**Tell us about your project below** 👇\n"
                "• **Project / server name**\n"
                "• **What it is about**\n"
                "• **What you offer in return**\n"
                "• **Your audience** — members, views, reach…\n"
                "• **Best way to reach you** + a link"
            ),
            "fr": (
                "**Parle-nous de ton projet ci-dessous** 👇\n"
                "• **Nom du projet / serveur**\n"
                "• **De quoi il s'agit**\n"
                "• **Ce que tu offres en retour**\n"
                "• **Ton audience** — membres, vues, portée…\n"
                "• **Meilleur moyen de te contacter** + un lien"
            ),
        },
        "color":  discord.ButtonStyle.secondary,
    },
    "question": {
        "label":  "Question",
        "emoji":  "❓",
        "style":  2,
        "accent": ui.TICKET_ACCENTS["question"],
        "prefix": "question",
        "header": {
            "en": "# 🌊 MyPineapple Support\n## GENERAL QUESTION",
            "fr": "# 🌊 MyPineapple Support\n## QUESTION GÉNÉRALE",
        },
        "guide": {
            "en": (
                "**Ask your question below** 👇\n"
                "-# The more context you give, the faster we can help."
            ),
            "fr": (
                "**Pose ta question ci-dessous** 👇\n"
                "-# Plus tu donnes de contexte, plus vite on peut t'aider."
            ),
        },
        "color":  discord.ButtonStyle.secondary,
    },
}

# ── Textes d'interface des tickets (bilingues) ───────────────────────────────
# Le salon s'ouvre en anglais (public international) ; le bouton bascule tout
# le message d'accueil dans l'autre langue, pour tout le monde.
DEFAULT_LANG = "en"
LANGS = ("en", "fr")

TICKET_UI = {
    "en": {
        "ticket":    "Ticket",
        "opened_by": "Opened by",
        "opened_at": "Opened at",
        "switch":    "🇫🇷 Français",   # libellé du bouton = langue vers laquelle on bascule
        "switch_to": "fr",
        "only_opener_staff": "Only the ticket opener and the staff can change the language.",
    },
    "fr": {
        "ticket":    "Ticket",
        "opened_by": "Ouvert par",
        "opened_at": "Ouvert le",
        "switch":    "🇬🇧 English",
        "switch_to": "en",
        "only_opener_staff": "Seul l'auteur du ticket et le staff peuvent changer la langue.",
    },
}

# custom_id du panel -> type de ticket (le clic ouvre directement le salon)
TICKET_BUTTONS = {f"ticket_{kind}": kind for kind in TICKET_TYPES}



def _build_overwrites(guild: discord.Guild, member: discord.Member) -> dict:
    support_role = guild.get_role(SUPPORT_ROLE_ID)
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
    return overwrites


def _is_image_url(url: str) -> bool:
    low = url.lower()
    return (
        "cdn.discordapp.com/attachments" in low
        or any(ext in low for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"))
    )


def _clip(text: str, limit: int) -> str:
    """Tronque proprement (l'API Discord refuse au-delà : erreur 50035)."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"



# Bouton de langue : custom_id fixe pour survivre aux redémarrages
# (une seule vue persistante pour tous les tickets, l'état vit en DB).
TICKET_LANG_BUTTON_ID = "ticket_lang_toggle"


def build_ticket_intro(
    kind: str,
    lang: str,
    number: int | None,
    opener_id: int,
    opened_ts: int,
) -> list[dict]:
    """Payload du message d'accueil d'un ticket (components v2).

    Contient : titre bilingue + logo, guide « ce qu'il faut nous dire » dans la
    langue courante, rappel du numéro/auteur/date, et le bouton qui bascule le
    message en EN/FR. Le message est réutilisé tel quel à chaque changement de
    langue (``api_edit``), donc une seule source de vérité.
    """
    type_info = TICKET_TYPES.get(kind, TICKET_TYPES["question"])
    lang = lang if lang in LANGS else DEFAULT_LANG
    strings = TICKET_UI.get(lang, TICKET_UI[DEFAULT_LANG])

    meta = (
        f"**{strings['ticket']}** `#{number}`\n"
        f"**{strings['opened_by']}** <@{opener_id}>\n"
        f"**{strings['opened_at']}** <t:{opened_ts}:F>"
    )

    return [
        {
            "type": 17,
            "accent_color": type_info["accent"],
            "components": [
                {
                    "type": 9,
                    "components": [
                        {"type": 10, "content": _clip(type_info["header"][lang], 3900)}
                    ],
                    "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                },
                {"type": 14, "divider": True, "spacing": 1},
                {"type": 10, "content": _clip(type_info["guide"][lang], 3900)},
                {"type": 14, "divider": True, "spacing": 1},
                {"type": 10, "content": meta},
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 2,
                            "label": _clip(strings["switch"], 80),
                            "custom_id": TICKET_LANG_BUTTON_ID,
                        }
                    ],
                },
            ],
        }
    ]


