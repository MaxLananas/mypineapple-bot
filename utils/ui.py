"""Design system — cartes (components v2) partagées par toutes les commandes.

Toutes les réponses du bot passent par ici pour avoir le même rendu :

    from utils import ui

    card = ui.card("## 🍍 Ping", accent=ui.ACCENT_BRAND, thumbnail=user.display_avatar.url)
    card.text("**Bot** `42 ms` · **API** `38 ms`")
    card.footer("Demandé par @Max")
    await ui.send(interaction, card)          # public par défaut

Pourquoi components v2 plutôt que des embeds : carte à accent coloré, sections
avec vignette, séparateurs, boutons dans la même carte, pied de page discret —
et surtout un rendu identique partout (tickets, logs, commandes).

Règles de la maison :
* **public par défaut** : tout le monde voit qui a lancé quoi. On passe
  ``ephemeral=True`` uniquement pour les commandes de modération/admin et les
  erreurs gênantes.
* pas de ping surprise : ``allowed_mentions`` est vidé par défaut.
* aucune limite Discord n'est franchie : le texte est tronqué en amont.
"""
from __future__ import annotations

import inspect
import json
import logging

import discord

log = logging.getLogger(__name__)

# ── Palette (une couleur par intention) ──────────────────────────────────────
ACCENT_BRAND   = 0x1E90FF   # bleu océan — commandes générales, tickets
ACCENT_OK      = 0x57F287   # vert — réussite
ACCENT_WARN    = 0xFEE75C   # jaune — avertissement
ACCENT_ERROR   = 0xED4245   # rouge — erreur / refus
ACCENT_INFO    = 0x9B8EC4   # violet doux — information, aide
ACCENT_FUN     = 0xF1C40F   # doré — fun, jeux, giveaways
ACCENT_LEVEL   = 0xF7CAC9   # rose corail — niveaux, XP, profils
ACCENT_MOD_WARN = 0xFFCC00  # ambre — avertissements de modération
ACCENT_LEVEL_UP = 0xA8D8EA  # bleu ciel — montée de niveau
ACCENT_LEVEL_ROLE = 0xC3B1E1  # violet doux — palier de niveau débloqué
ACCENT_MAX     = 0xFFD700   # or — niveau maximum atteint
ACCENT_MOD     = 0xED4245   # rouge — modération
ACCENT_LOG     = 0x2C3E50   # bleu nuit — logs / audit
ACCENT_INVITE  = 0x1ABC9C   # turquoise — invitations, parrainage

# — Une couleur par type de ticket (voir cogs/tickets/constants.py) —
TICKET_ACCENTS = {
    "commission":  0x1E90FF,
    "recruitment": 0x9B59B6,
    "bug":         0xED4245,
    "partnership": 0x57F287,
    "question":    0xF7CAC9,
}

MAX_TEXT = 4000             # limite Discord d'un bloc de texte (TextDisplay)
MAX_CONTENT = 4000          # limite globale d'un message components v2


def clip(text: str, limit: int = MAX_TEXT) -> str:
    """Tronque un texte à la limite Discord (sinon : 400 / 50035)."""
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


# ── Carte ────────────────────────────────────────────────────────────────────

# Types autorisés comme enfants d'un container (components v2). Un bouton ou
# un menu doit passer par une Action Row (type 1) : sinon Discord refuse le
# message avec un 400 Invalid Form Body.
CONTAINER_CHILD_TYPES = {1, 9, 10, 11, 12, 13, 14, 17}
ROW_CHILD_TYPES = {2, 3, 4, 5, 6, 7, 8}   # boutons et menus (dans une rangée)
NON_ROW_ITEMS = (discord.ui.Button, discord.ui.Select)


def wrap_items(elements, *, per_row: int = 5) -> list[discord.ui.ActionRow]:
    """Range des items dans des Action Rows valides.

    - les menus (selects) occupent leur propre rangée (Discord l'impose) ;
    - les boutons sont groupés par ``per_row`` (5 maximum).
    """
    rows: list[discord.ui.ActionRow] = []
    current: discord.ui.ActionRow | None = None

    for element in elements:
        if isinstance(element, discord.ui.Select):
            rows.append(discord.ui.ActionRow(element))
            current = None
            continue
        if not isinstance(element, discord.ui.Button):
            if isinstance(element, discord.ui.ActionRow):
                rows.append(element)
            continue
        if current is None or len(current.children) >= per_row:
            current = discord.ui.ActionRow()
            rows.append(current)
        current.add_item(element)
    return [row for row in rows if row.children]


def to_items(children) -> list[discord.ui.Item]:
    """Récupère les items dispatchables d'une vue (boutons, menus)."""
    items: list[discord.ui.Item] = []
    for child in children:
        if isinstance(child, NON_ROW_ITEMS):
            items.append(child)
        elif hasattr(child, "children"):
            items.extend(to_items(child.children))
    return items


def loose_items(view) -> list[str]:
    """Items (boutons/menus) pas rangés dans une Action Row — interdit.

    ``Card`` les range automatiquement avant l'envoi (filet de sécurité), donc
    ce contrôle sert surtout aux tests : il faut corriger la source, pas
    seulement masquer le problème.
    """
    found: list[str] = []

    def walk(container: discord.ui.Container, path: str) -> None:
        for i, child in enumerate(container.children):
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                found.append(f"{path}[{i}] {type(child).__name__}")
            elif isinstance(child, discord.ui.Container):
                walk(child, f"{path}[{i}]")

    for i, child in enumerate(getattr(view, "children", [])):
        if isinstance(child, discord.ui.Container):
            walk(child, f"container[{i}]")
    # items qui ont dû être rangés automatiquement à l'envoi : la source est à
    # corriger (le rendu n'a pas planté grâce au filet de sécurité).
    found.extend(f"{name} (rerangé automatiquement)" for name in
                 getattr(view, "_loose_fixed", []))
    return found


def validate(view_or_payload) -> None:
    """Vérifie la structure d'une carte avant envoi (règles Discord v2).

    Lève ``ValueError`` avec un message précis : c'est ce qui permet d'attraper
    en test un bouton mal rangé au lieu de le découvrir en production.
    """
    loose = loose_items(view_or_payload)
    if loose:
        raise ValueError(
            "bouton/menu à nu dans un container (Discord refuse : 400 Invalid Form Body) : "
            + ", ".join(loose) + " — utilise ui.Card.items()/row()."
        )

    blocks = (view_or_payload.to_components() if hasattr(view_or_payload, "to_components")
              else view_or_payload.get("components", []) if isinstance(view_or_payload, dict)
              else view_or_payload)

    def walk(children: list[dict], where: str) -> None:
        for i, child in enumerate(children or []):
            kind = child.get("type")
            if where == "container" and kind not in CONTAINER_CHILD_TYPES:
                raise ValueError(
                    f"components[{where}][{i}] : le type {kind} doit être rangé dans une "
                    "Action Row (type 1) — utilise ui.Card.items()/row()."
                )
            if kind == 1:
                row_children = child.get("components") or []
                if not row_children:
                    raise ValueError(f"components[{where}][{i}] : Action Row vide.")
                for j, comp in enumerate(row_children):
                    if comp.get("type") not in ROW_CHILD_TYPES:
                        raise ValueError(
                            f"components[{where}][{i}].components[{j}] : le type "
                            f"{comp.get('type')} n'a rien à faire dans une Action Row."
                        )
                continue        # le contenu d'une rangée a ses propres règles
            if kind == 10 and not (child.get("content") or "").strip():
                raise ValueError(f"components[{where}][{i}] : bloc de texte vide.")
            if kind in (9, 17):
                walk(child.get("components"), "container" if kind == 17 else where)

    walk(blocks, "message")

class Card(discord.ui.LayoutView):
    """Carte à accent coloré : sections, séparateurs, boutons, pied de page.

    C'est une ``View`` : elle se passe directement à ``send_message(view=…)``
    et à ``edit_original_response(view=…)``.
    """

    def __init__(
        self,
        title: str | None = None,
        *,
        accent: int = ACCENT_BRAND,
        thumbnail: str | None = None,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)
        self._accent = accent
        self._loose_fixed: list[str] = []   # items rerangés automatiquement
        self.container = discord.ui.Container(accent_colour=discord.Colour(accent))
        self.add_item(self.container)
        if title:
            self.header(title, thumbnail=thumbnail)

    # ── Construction ──
    def header(self, content: str, *, thumbnail: str | None = None) -> "Card":
        """Titre (+ vignette optionnelle : avatar, logo…)."""
        text = discord.ui.TextDisplay(clip(content))
        if thumbnail:
            self.container.add_item(discord.ui.Section(
                text, accessory=discord.ui.Thumbnail(thumbnail),
            ))
        else:
            self.container.add_item(text)
        return self

    def text(self, content: str) -> "Card":
        """Bloc de texte (markdown Discord autorisé)."""
        if content:
            self.container.add_item(discord.ui.TextDisplay(clip(content)))
        return self

    def fields(self, *pairs: tuple[str, object], separator: str = "\n") -> "Card":
        """Champs « **Nom** valeur » empilés dans un bloc de texte."""
        lines = [f"**{name}** {value}" for name, value in pairs if value is not None]
        return self.text(separator.join(lines)) if lines else self

    def columns(self, *pairs: tuple[str, object], per_line: int = 3) -> "Card":
        """Champs alignés sur une ligne : ``**Nom** valeur · **Nom** valeur``."""
        cells = [" · ".join(f"**{n}** {v}" for n, v in pairs[i:i + per_line])
                 for i in range(0, len(pairs), per_line)]
        return self.text("\n".join(cells)) if cells else self

    def divider(self, *, spacing: int = 1, visible: bool = True) -> "Card":
        """Séparateur (``spacing`` : 1 = petit, 2 = grand)."""
        self.container.add_item(discord.ui.Separator(
            spacing=discord.SeparatorSpacing.large if spacing > 1
            else discord.SeparatorSpacing.small,
            visible=visible,
        ))
        return self

    def media(self, *items: tuple[str, str | None]) -> "Card":
        """Galerie d'images (au plus 10)."""
        clean = [(u, d) for u, d in items if u][:10]
        if clean:
            self.container.add_item(discord.ui.MediaGallery(
                *[discord.MediaGalleryItem(u, description=d) for u, d in clean]
            ))
        return self

    def row(self, *items: discord.ui.Item) -> "Card":
        """Rangée d'items (boutons, menus) dans la carte."""
        action_row = discord.ui.ActionRow()
        for item in items:
            action_row.add_item(item)
        self.container.add_item(action_row)
        return self

    def items(self, *elements: discord.ui.Item, per_row: int = 5) -> "Card":
        """Ajoute des items (boutons, menus, sélecteurs) **dans des rangées**.

        Indispensable : un bouton ou un menu posé directement dans un container
        (sans Action Row) est refusé par Discord (400 Invalid Form Body). Cette
        méthode range les menus chacun sur leur propre rangée et les boutons
        par paquets de ``per_row``.
        """
        for action_row in wrap_items(elements, per_row=per_row):
            self.container.add_item(action_row)
        return self

    def button(
        self,
        label: str,
        *,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        emoji: str | None = None,
        custom_id: str | None = None,
        url: str | None = None,
        callback=None,
        disabled: bool = False,
    ) -> "Card":
        """Ajoute un bouton (dans sa propre rangée).

        ``callback`` rend le bouton interactif ; sinon on utilise ``custom_id``
        (permet de le rattraper par une vue persistante déjà enregistrée).
        Le callback peut accepter ``(interaction)`` — la convention de
        discord.py — ou ``(interaction, button)`` : les deux marchent.
        """
        if url:
            button = discord.ui.Button(label=clip(label, 80), style=discord.ButtonStyle.link,
                                       emoji=emoji, url=url)
        else:
            button = discord.ui.Button(
                label=clip(label, 80), style=style, emoji=emoji,
                custom_id=custom_id, disabled=disabled,
            )
            if callback is not None:
                # discord.py appelle les callbacks avec le seul argument
                # ``interaction`` : on adapte ceux qui attendent le bouton.
                params = [p for p in inspect.signature(callback).parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
                if len(params) >= 2:
                    async def _wrapped(interaction, _cb=callback, _btn=button):
                        await _cb(interaction, _btn)
                    button.callback = _wrapped
                else:
                    button.callback = callback
        return self.row(button)

    def links(self, *entries: tuple[str, str, str | None]) -> "Card":
        """Rangée de boutons-liens : ``(label, url, emoji)``."""
        row = discord.ui.ActionRow()
        for label, url, emoji in entries[:5]:
            row.add_item(discord.ui.Button(
                label=clip(label, 80), url=url, emoji=emoji,
                style=discord.ButtonStyle.link,
            ))
        self.container.add_item(row)
        return self

    def footer(self, content: str) -> "Card":
        """Pied de page discret (petit texte gris)."""
        return self.text(f"-# {clip(content, 1000)}")

    # ── Sortie ──
    def _normalize_rows(self) -> None:
        """Range les items à nu (boutons, menus) dans des Action Rows.

        Filet de sécurité : Discord refuse un message dont un bouton ou un menu
        est posé directement dans un container (400 Invalid Form Body). Même si
        un appelant les ajoute sans rangée, le payload partira valide.
        """
        def fix(container: discord.ui.Container) -> None:
            children = list(container.children)
            has_container = any(isinstance(c, discord.ui.Container) for c in children)
            loose = any(isinstance(c, (discord.ui.Button, discord.ui.Select))
                        for c in children)
            if loose:
                # Trace du rangement automatique : les tests s'en servent pour
                # signaler le code fautif à la source.
                self._loose_fixed.extend(
                    type(c).__name__ for c in children
                    if isinstance(c, (discord.ui.Button, discord.ui.Select))
                )
            if has_container:
                for child in children:
                    if isinstance(child, discord.ui.Container):
                        fix(child)
            if not loose:
                return
            container.clear_items()
            pending: list[discord.ui.Item] = []
            for child in children:
                if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                    pending.append(child)
                    continue
                for action_row in wrap_items(pending):
                    container.add_item(action_row)
                pending = []
                container.add_item(child)
            for action_row in wrap_items(pending):
                container.add_item(action_row)

        fix(self.container)

    def to_components(self):
        self._normalize_rows()
        return super().to_components()

    def payload(self) -> dict:
        """Payload brut, pour ``utils.api.api_send`` (file d'attente, logs…)."""
        return {"flags": 32768, "components": self.to_components()}


def card(title: str | None = None, **kwargs) -> Card:
    """Raccourci : ``ui.card("## Titre", accent=ui.ACCENT_OK)``."""
    return Card(title, **kwargs)


# ── Cartes prêtes à l'emploi ─────────────────────────────────────────────────

def ok_card(title: str, body: str | None = None, *, footer: str | None = None) -> Card:
    c = Card(f"## {title}", accent=ACCENT_OK)
    if body:
        c.text(body)
    if footer:
        c.divider().footer(footer)
    return c


def warn_card(title: str, body: str | None = None, *, footer: str | None = None) -> Card:
    c = Card(f"## {title}", accent=ACCENT_WARN)
    if body:
        c.text(body)
    if footer:
        c.divider().footer(footer)
    return c


def error_card(title: str, body: str | None = None, *, footer: str | None = None) -> Card:
    c = Card(f"## {title}", accent=ACCENT_ERROR)
    if body:
        c.text(body)
    if footer:
        c.divider().footer(footer)
    return c


def info_card(title: str, body: str | None = None, *, footer: str | None = None) -> Card:
    c = Card(f"## {title}", accent=ACCENT_INFO)
    if body:
        c.text(body)
    if footer:
        c.divider().footer(footer)
    return c


# ── Attribution ──────────────────────────────────────────────────────────────

def signature(interaction: discord.Interaction, *, extra: str | None = None) -> str:
    """Pied de page « qui a lancé la commande » : personne ne se demande plus qui c'est."""
    user = interaction.user
    parts = ["🍍 MyPineapple", f"requested by {user.display_name}"]
    if extra:
        parts.append(extra)
    return " · ".join(parts)


# ── Envoi / édition ──────────────────────────────────────────────────────────

def _none_mentions() -> discord.AllowedMentions:
    return discord.AllowedMentions.none()


async def send(
    interaction: discord.Interaction,
    view: Card | discord.ui.LayoutView,
    *,
    ephemeral: bool = False,
    mentions: discord.AllowedMentions | None = None,
) -> discord.Message | None:
    """Répond avec une carte, que l'interaction ait déjà été différée ou non.

    Public par défaut (tout le monde voit la réponse et son auteur).
    """
    allowed = mentions or _none_mentions()
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(view=view, ephemeral=ephemeral,
                                                   allowed_mentions=allowed)
        return await interaction.response.send_message(view=view, ephemeral=ephemeral,
                                                       allowed_mentions=allowed)
    except discord.HTTPException as exc:
        # Une carte refusée ne doit pas laisser l'utilisateur devant
        # « Interaction failed » — mais l'erreur réelle est tracée, sinon
        # impossible de savoir ce que Discord n'a pas aimé.
        log.error(
            "carte refusée par Discord pour /%s : %s %s — %s",
            getattr(getattr(interaction, "command", None), "qualified_name", "?"),
            getattr(exc, "status", "?"), getattr(exc, "code", "?"),
            (getattr(exc, "text", "") or str(exc))[:500],
        )
        try:
            log.error("payload refusé : %s", json.dumps(
                view.payload() if isinstance(view, Card) else view.to_components()
            )[:1500])
        except Exception:
            pass

        fallback = error_card("❌ Couldn't render that",
                              "The reply could not be displayed. Try again in a moment.")
        try:
            if interaction.response.is_done():
                return await interaction.followup.send(view=fallback, ephemeral=True)
            return await interaction.response.send_message(view=fallback, ephemeral=True)
        except discord.HTTPException:
            # L'accusé de réception n'est plus possible (interaction déjà
            # répondue, canal fermé…) : on tente le followup, seul recours.
            try:
                return await interaction.followup.send(view=fallback, ephemeral=True)
            except discord.HTTPException:
                log.error("repli impossible : l'interaction n'est plus valide")
                return None


async def edit(
    interaction: discord.Interaction,
    view: Card | discord.ui.LayoutView,
) -> discord.Message | None:
    """Remplace le contenu du message d'origine par une nouvelle carte."""
    try:
        return await interaction.edit_original_response(view=view)
    except discord.HTTPException:
        return None


async def error(interaction: discord.Interaction, message: str, *, ephemeral: bool = True,
                title: str = "❌ That didn't work") -> None:
    """Erreur standardisée (discrète par défaut : personne n'a besoin de la voir)."""
    await send(interaction, error_card(title, message), ephemeral=ephemeral)


async def note(interaction: discord.Interaction, title: str, message: str, *,
               accent: int = ACCENT_INFO, ephemeral: bool = False) -> None:
    """Petite carte d'information standardisée."""
    await send(interaction, Card(f"## {title}", accent=accent).text(message),
               ephemeral=ephemeral)


# ── Conversion depuis les payloads bruts existants ───────────────────────────

def _raw_to_items(blocks: list[dict]) -> list[discord.ui.Item]:
    """Reconstruit les blocs d'un payload components v2 en composants natifs."""
    items: list[discord.ui.Item] = []
    for block in blocks or []:
        kind = block.get("type")
        if kind == 10:                                   # texte
            content = block.get("content") or ""
            if content:
                items.append(discord.ui.TextDisplay(clip(content)))
        elif kind == 14:                                 # séparateur
            items.append(discord.ui.Separator(
                spacing=discord.SeparatorSpacing.large
                if (block.get("spacing") or 1) > 1 else discord.SeparatorSpacing.small,
                visible=block.get("divider", True),
            ))
        elif kind == 9:                                  # section + vignette
            texts = [discord.ui.TextDisplay(clip(c.get("content") or ""))
                     for c in block.get("components", []) if c.get("type") == 10
                     and (c.get("content") or "").strip()]
            if not texts:
                continue
            accessory = block.get("accessory") or {}
            url = (accessory.get("media") or {}).get("url") if accessory.get("type") == 11 else None
            items.append(discord.ui.Section(
                *texts, accessory=discord.ui.Thumbnail(url) if url else None,
            ))
        elif kind == 12:                                 # galerie d'images
            media = [(i.get("media", {}).get("url"), i.get("description"))
                     for i in block.get("items", []) if i.get("media", {}).get("url")]
            if media:
                items.append(discord.ui.MediaGallery(
                    *[discord.MediaGalleryItem(u, description=d) for u, d in media[:10]]
                ))
        elif kind == 1:                                  # rangée de boutons
            row = discord.ui.ActionRow()
            for comp in block.get("components", []):
                if comp.get("type") != 2:
                    continue
                label = clip(comp.get("label") or "", 80)
                emoji = (comp.get("emoji") or {}).get("name")
                if comp.get("url"):
                    row.add_item(discord.ui.Button(label=label, url=comp["url"], emoji=emoji,
                                                   style=discord.ButtonStyle.link))
                else:
                    row.add_item(discord.ui.Button(
                        label=label, emoji=emoji,
                        style=discord.ButtonStyle(comp.get("style", 2)),
                        custom_id=comp.get("custom_id"), disabled=bool(comp.get("disabled")),
                    ))
            if row.children:
                items.append(row)
    return items


def polish(
    payload: dict,
    *,
    accent: int | None = None,
    title: str | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
) -> Card:
    """Convertit un ancien payload components v2 en ``Card`` du design system.

    Permet de reprendre les commandes déjà écrites en payload brut sans les
    réécrire : on récupère les blocs, on impose l'accent et on ajoute le pied de
    page « demandé par … » (l'attribution qui manquait).
    """
    containers = [c for c in (payload.get("components") or []) if c.get("type") == 17]
    result = Card(
        None,
        accent=accent if accent is not None else
        (containers[0].get("accent_color") if containers else ACCENT_BRAND),
    )
    if title:
        result.header(title, thumbnail=thumbnail)

    for container in containers or []:
        for item in _raw_to_items(container.get("components", [])):
            result.container.add_item(item)
    if footer:
        result.divider(spacing=1).footer(footer)
    return result


async def send_raw(
    interaction: discord.Interaction,
    payload: dict,
    *,
    ephemeral: bool = False,
    accent: int | None = None,
    title: str | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
    sign: bool = True,
) -> discord.Message | None:
    """Envoie un ancien payload brut **en réponse à l'interaction**, en carte.

    C'est le pont utilisé pour migrer les commandes : au lieu d'envoyer un
    message détaché dans le salon après un ``defer(ephemeral=True)``, le bot
    répond vraiment — donc tout le monde voit qui a lancé la commande.
    """
    card = polish(
        payload,
        accent=accent,
        title=title,
        thumbnail=thumbnail or (interaction.user.display_avatar.url if sign else None),
        footer=footer if footer is not None else
        (signature(interaction) if sign else None),
    )
    return await send(interaction, card, ephemeral=ephemeral)


def from_embed(
    embed: discord.Embed,
    *,
    accent: int | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
) -> Card:
    """Convertit un embed en carte, pour migrer une commande sans la réécrire.

    - titre → titre de la carte (+ vignette)
    - auteur de l'embed → « demandé par X »
    - description / champs / footer → blocs de texte
    """
    title = embed.title or ""
    c = Card(f"## {title}" if title and not title.startswith("#") else (title or None),
             accent=accent if accent is not None else (embed.colour.value if embed.colour else ACCENT_BRAND),
             thumbnail=thumbnail or (embed.thumbnail.url if embed.thumbnail else None))

    author = getattr(embed, "author", None)
    if author and author.name:
        c.text(f"**{author.name}**")

    if embed.description:
        c.text(embed.description)

    for field in embed.fields:
        c.divider(spacing=1)
        c.text(f"**{field.name}**\n{field.value}")

    parts = []
    if footer:
        parts.append(footer)
    if embed.footer and embed.footer.text:
        parts.append(embed.footer.text)
    if parts:
        c.divider(spacing=1).footer(" · ".join(parts))
    return c
