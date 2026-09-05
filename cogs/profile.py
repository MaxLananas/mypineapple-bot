from __future__ import annotations
import logging
import random
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import utils.db as db
from utils.api import api_send, get_session
from utils.helpers import xp_for_level, progress_bar, ts_now
from utils.leveling import add_xp, level_roles, level_role_name
from config import (
    LOGO_URL,
    PORTFOLIO_FILES, RELEASE_BASE, CREDITS,
    REVIEW_FORUM_ID, WEBSITE_URL, YOUTUBE_URL, INSTAGRAM_URL,
    SUPPORT_ROLE_ID,
    REVIEW_TAG_5STARS, REVIEW_TAG_4STARS, REVIEW_TAG_3STARS,
    REVIEW_TAG_2STARS, REVIEW_TAG_1STAR,
    REVIEW_TAG_BUILD, REVIEW_TAG_PLUGIN, REVIEW_TAG_PARTNER,
)

log = logging.getLogger(__name__)

DAILY_XP_MIN = 50
DAILY_XP_MAX = 100

STAR_TAG_MAP = {
    5: REVIEW_TAG_5STARS,
    4: REVIEW_TAG_4STARS,
    3: REVIEW_TAG_3STARS,
    2: REVIEW_TAG_2STARS,
    1: REVIEW_TAG_1STAR,
}

SERVICE_TAG_MAP = {
    "build":       REVIEW_TAG_BUILD,
    "plugin":      REVIEW_TAG_PLUGIN,
    "partnership": REVIEW_TAG_PARTNER,
}

SERVICE_LABELS = {
    "build":       "🏗️ Build",
    "plugin":      "🔌 Plugin / Mod",
    "mod":         "🔌 Plugin / Mod",
    "server":      "⚙️ Server Setup",
    "config":      "⚙️ Server Config",
    "partnership": "🤝 Partnership",
    "formation":   "📚 Formation / Coaching",
    "other":       "🌊 Other",
}


def _is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


async def _create_forum_thread_via_rest(
    forum_id:      int,
    thread_name:   str,
    tag_ids:       list[int],
    components:    list[dict],
    auto_archive:  int = 10080,
) -> dict:
    session = get_session()
    url     = f"https://discord.com/api/v10/channels/{forum_id}/threads"
    payload = {
        "name":                  thread_name,
        "auto_archive_duration": auto_archive,
        "applied_tags":          [str(t) for t in tag_ids if t],
        "message": {
            "flags":      32768,
            "components": components,
        },
    }
    async with session.post(url, json=payload) as r:
        try:
            data = await r.json()
        except Exception:
            data = {}
        if r.status not in (200, 201):
            log.warning("create_forum_thread → %s %s", r.status, data)
        return data


async def _post_review_to_forum(
    guild:        discord.Guild,
    member:       discord.Member,
    stars:        int,
    project:      str,
    content:      str,
    service_type: str,
    budget:       str | None = None,
    recommend:    str | None = None,
    image_url:    str | None = None,
) -> discord.Thread | None:
    forum = guild.get_channel(REVIEW_FORUM_ID)
    if not forum or not isinstance(forum, discord.ForumChannel):
        log.warning("Review forum %d not found.", REVIEW_FORUM_ID)
        return None

    star_display   = "⭐" * stars + "☆" * (5 - stars)
    service_label  = SERVICE_LABELS.get(service_type, "🌊 Other")
    ts             = ts_now()

    tag_ids: list[int] = []
    star_tag = STAR_TAG_MAP.get(stars, 0)
    if star_tag:
        tag_ids.append(star_tag)
    svc_tag = SERVICE_TAG_MAP.get(service_type, 0)
    if svc_tag and svc_tag not in tag_ids:
        tag_ids.append(svc_tag)

    recommend_line = ""
    if recommend:
        rec_map = {"yes": "✅ Yes", "no": "❌ No", "maybe": "🤔 Maybe"}
        recommend_line = f"\n**Would recommend?** {rec_map.get(recommend, recommend)}"

    budget_line = f"\n**Budget paid** {budget}" if budget else ""

    components_inner = [
        {
            "type": 9,
            "components": [
                {
                    "type": 10,
                    "content": (
                        f"## {star_display}\n"
                        f"**Project** {project}\n"
                        f"**Service** {service_label}"
                        f"{budget_line}"
                        f"{recommend_line}"
                    ),
                }
            ],
            "accessory": {
                "type": 11,
                "media": {"url": str(member.display_avatar.url)},
            },
        },
        {"type": 14, "divider": True, "spacing": 1},
        {"type": 10, "content": content},
    ]

    if image_url:
        components_inner.append({
            "type": 12,
            "items": [{"media": {"url": image_url}, "description": "Review screenshot"}],
        })

    components_inner += [
        {"type": 14, "divider": True, "spacing": 1},
        {
            "type": 10,
            "content": (
                f"**By** {member.mention} (`{member.id}`)\n"
                f"**On** <t:{ts}:F>"
            ),
        },
    ]

    full_components = [
        {"type": 17, "accent_color": 0xFFD700, "components": components_inner}
    ]

    thread_name = f"{star_display} {member.display_name} · {project[:35]}"

    resp = await _create_forum_thread_via_rest(
        forum_id    = REVIEW_FORUM_ID,
        thread_name = thread_name,
        tag_ids     = tag_ids,
        components  = full_components,
    )

    thread_id = resp.get("id")
    if not thread_id:
        log.error("Forum thread creation failed: %s", resp)
        return None

    thread = guild.get_thread(int(thread_id))
    if not thread:
        try:
            thread = await guild.fetch_channel(int(thread_id))
        except Exception as e:
            log.error("Cannot fetch thread %s: %s", thread_id, e)
            return None

    support_role = guild.get_role(SUPPORT_ROLE_ID)
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=True,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_threads=True,
            ),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
            )
        await thread.edit(overwrites=overwrites)
    except Exception as e:
        log.warning("Could not set thread overwrites: %s", e)

    log.info("Review thread created: %s (%s)", thread_name, thread_id)
    return thread


class PortfolioView(discord.ui.View):
    """Portfolio paginé en DM (boutons ← →)."""

    def __init__(self, entries: list[dict], author: discord.User, total_builds: int, collab_text: str):
        super().__init__(timeout=600)
        self.entries = entries
        self.author = author
        self.total_builds = total_builds
        self.collab_text = collab_text
        self.page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= len(self.entries) - 1

    def build_embed(self) -> discord.Embed:
        entry  = self.entries[self.page]
        credit = entry.get("credit")
        credit_info = CREDITS.get(credit) if credit else None
        caption = f"Collaboration: {credit_info['label']}" if credit_info else "Personal build"

        embed = discord.Embed(
            title=f"🏗️ Portfolio — MaxLananas",
            description=(
                f"**{self.total_builds} builds** · page **{self.page + 1}/{len(self.entries)}**\n"
                f"-# {caption}"
            ),
            color=0x1E90FF,
        )
        embed.set_image(url=RELEASE_BASE + entry["name"])
        embed.add_field(
            name="🔗 Links",
            value=f"[Website]({WEBSITE_URL}) · [YouTube]({YOUTUBE_URL}) · [Instagram]({INSTAGRAM_URL})",
            inline=False,
        )
        embed.add_field(name="🤝 Collaborations", value=self.collab_text, inline=False)
        embed.set_footer(text=f"Requested by {self.author}")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="portfolio_prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="portfolio_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(len(self.entries) - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class ReviewStep1(discord.ui.Modal, title="Review — Step 1 / 2"):
    project = discord.ui.TextInput(
        label="Project / commission name",
        style=discord.TextStyle.short,
        placeholder="e.g. Medieval spawn build",
        max_length=100,
    )
    rating = discord.ui.TextInput(
        label="Rating (1 to 5 stars)",
        style=discord.TextStyle.short,
        placeholder="5",
        max_length=1,
    )
    content = discord.ui.TextInput(
        label="Your review",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your experience — quality, communication, delays…",
        max_length=1000,
    )
    budget = discord.ui.TextInput(
        label="Budget paid (optional)",
        style=discord.TextStyle.short,
        placeholder="e.g. 25€ or 'Free collab'",
        required=False,
        max_length=50,
    )
    image_url = discord.ui.TextInput(
        label="Screenshot URL (optional)",
        style=discord.TextStyle.short,
        placeholder="https://imgur.com/...",
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.rating.value.strip()
        try:
            stars = int(raw)
        except ValueError:
            stars = 0
        if not 1 <= stars <= 5:
            await interaction.response.send_message(
                "❌ Rating must be a whole number between **1** and **5**. Please try again.",
                ephemeral=True,
            )
            return

        img       = self.image_url.value.strip() if self.image_url.value else None
        valid_img = img if img and _is_valid_url(img) else None

        view = ReviewStep2View(
            project  = self.project.value,
            stars    = stars,
            content  = self.content.value,
            budget   = self.budget.value.strip() if self.budget.value else None,
            image_url= valid_img,
        )

        await interaction.response.send_message(
            content=(
                f"**Step 2 / 2** — Select the service type and your recommendation.\n"
                f"-# Project: *{self.project.value}* · {stars}⭐"
            ),
            view=view,
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("ReviewStep1: %s", error)
        try:
            await interaction.response.send_message("An error occurred.", ephemeral=True)
        except Exception:
            pass


class ReviewStep2View(discord.ui.View):
    def __init__(self, project: str, stars: int, content: str, budget: str | None, image_url: str | None):
        super().__init__(timeout=300)
        self.project   = project
        self.stars     = stars
        self.content   = content
        self.budget    = budget
        self.image_url = image_url
        self.service   = "other"
        self.recommend = "yes"

        self.service_select.placeholder = "Select service type…"
        self.recommend_select.placeholder = "Would you recommend MaxLananas?"

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="Select service type…",
        custom_id="review_service",
        options=[
            discord.SelectOption(label="🏗️ Build",               value="build",       description="Minecraft build commission"),
            discord.SelectOption(label="🔌 Plugin / Mod",         value="plugin",      description="Plugin or mod development"),
            discord.SelectOption(label="⚙️ Server Setup / Config", value="server",      description="Server setup or configuration"),
            discord.SelectOption(label="📚 Formation / Coaching",  value="formation",   description="Training or coaching session"),
            discord.SelectOption(label="🤝 Partnership",           value="partnership", description="Collaboration or partnership"),
            discord.SelectOption(label="🌊 Other",                 value="other",       description="Something else"),
        ],
        min_values=1,
        max_values=1,
    )
    async def service_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.service = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="Would you recommend MaxLananas?",
        custom_id="review_recommend",
        options=[
            discord.SelectOption(label="✅ Yes, absolutely!",  value="yes",   emoji="✅"),
            discord.SelectOption(label="🤔 Maybe / Depends",   value="maybe", emoji="🤔"),
            discord.SelectOption(label="❌ No",                value="no",    emoji="❌"),
        ],
        min_values=1,
        max_values=1,
    )
    async def recommend_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.recommend = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Submit Review ⭐", style=discord.ButtonStyle.success, emoji="📝")
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        thread = await _post_review_to_forum(
            guild        = interaction.guild,
            member       = interaction.user,
            stars        = self.stars,
            project      = self.project,
            content      = self.content,
            service_type = self.service,
            budget       = self.budget,
            recommend    = self.recommend,
            image_url    = self.image_url,
        )

        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(
            content="✓ Review submitted!",
            view=self,
        )

        if thread:
            await interaction.followup.send(
                f"✓ Your review has been posted in {thread.mention} — thank you! 🍍",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "✓ Review submitted! Thank you for your feedback. 🍍",
                ephemeral=True,
            )


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Display your complete profile card.")
    @app_commands.describe(member="Member to inspect (default: yourself).")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target   = member or interaction.user
        data     = db.levels()
        guild_id = str(interaction.guild_id)
        user_id  = str(target.id)

        ud     = data.get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})
        level  = ud["level"]
        xp     = ud["xp"]
        needed = xp_for_level(level)
        bar    = progress_bar(xp, needed)
        pct    = int((xp / needed) * 100) if needed else 0

        all_u   = data.get(guild_id, {})
        sorted_ = sorted(all_u.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
        rank_n  = next((i + 1 for i, (uid, _) in enumerate(sorted_) if uid == user_id), "?")

        role_name = None
        for ms in sorted(level_roles(), reverse=True):
            if level >= ms:
                role_name = level_role_name(ms)
                break

        daily_data   = db.daily()
        user_daily   = daily_data.get(guild_id, {}).get(user_id, {})
        streak       = user_daily.get("streak", 0)
        total_claims = user_daily.get("total_claims", 0)

        joined  = int(target.joined_at.timestamp()) if target.joined_at else 0
        created = int(target.created_at.timestamp())
        roles   = [r.mention for r in reversed(target.roles) if r.name != "@everyone"][:5]
        roles_text = " ".join(roles) if roles else "None"

        next_ml = next((l for l in sorted(level_roles()) if l > level), None)
        ml_text = f"Next milestone: level **{next_ml}**" if next_ml else "🏆 Maximum level reached!"

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xC3B1E1,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## {target.display_name}\n`{target}` · Rank `#{rank_n}`",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(target.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Level** `{level}` {f'· {role_name}' if role_name else ''}\n"
                                f"`{bar}` **{pct}%** — `{xp}` / `{needed}` XP\n"
                                f"-# {ml_text}"
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Daily Streak** 🔥 `{streak}` day(s)\n"
                                f"**Total dailies claimed** `{total_claims}`"
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Account created** <t:{created}:D>\n"
                                f"**Joined server** <t:{joined}:D>\n"
                                f"**Roles** {roles_text}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="daily", description="Claim your daily XP reward.")
    async def daily(self, interaction: discord.Interaction):
        now      = datetime.now(timezone.utc)
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        data      = db.daily()
        user_data = data.setdefault(guild_id, {}).setdefault(user_id, {
            "last_claim": None, "streak": 0, "total_claims": 0,
        })

        last_str = user_data.get("last_claim")
        if last_str:
            last = datetime.fromisoformat(last_str)
            diff = (now - last).total_seconds()
            if diff < 86400:
                remaining = int(86400 - diff)
                h, m = divmod(remaining // 60, 60)
                await interaction.response.send_message(
                    f"⏳ Come back in **{h}h {m}m** for your next daily!", ephemeral=True
                )
                return
            streak = user_data["streak"] + 1 if diff < 172800 else 1
        else:
            streak = 1

        xp_gain = random.randint(DAILY_XP_MIN, DAILY_XP_MAX)
        if streak >= 7:
            xp_gain = int(xp_gain * 1.5)
        elif streak >= 3:
            xp_gain = int(xp_gain * 1.2)

        user_data["last_claim"]   = now.isoformat()
        user_data["streak"]       = streak
        user_data["total_claims"] = user_data.get("total_claims", 0) + 1
        db.save_daily(data)

        await add_xp(
            guild=interaction.guild,
            member=interaction.user,
            amount=xp_gain,
            channel=interaction.channel,
        )
        ud = db.levels().get(guild_id, {}).get(user_id, {"xp": 0, "level": 0})

        streak_bonus = ""
        if streak >= 7:
            streak_bonus = " 🔥 **+50% legendary streak bonus!**"
        elif streak >= 3:
            streak_bonus = " 🔥 **+20% streak bonus!**"

        ts = ts_now()
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFD700,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": (
                                        f"## 🎁 Daily Claimed!\n"
                                        f"{interaction.user.mention} collected their daily reward."
                                    ),
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(interaction.user.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**+{xp_gain} XP**{streak_bonus}\n"
                                f"**Streak** 🔥 `{streak}` consecutive day(s)\n"
                                f"**Current level** `{ud['level']}`\n\n"
                                f"-# Come back tomorrow to keep your streak! <t:{ts}:R>"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="streak", description="Display your daily login streak.")
    @app_commands.describe(member="Member to inspect (default: yourself).")
    async def streak(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target   = member or interaction.user
        guild_id = str(interaction.guild_id)
        user_id  = str(target.id)

        data      = db.daily()
        user_data = data.get(guild_id, {}).get(user_id, {})
        streak    = user_data.get("streak", 0)
        last_str  = user_data.get("last_claim")
        total     = user_data.get("total_claims", 0)

        last_text = (
            f"Last daily: <t:{int(datetime.fromisoformat(last_str).timestamp())}:R>"
            if last_str else "No daily claimed yet."
        )
        filled = min(streak, 7)
        bar    = "🔥" * filled + "⬜" * (7 - filled)

        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFF6B35,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": f"## 🔥 {target.display_name}'s Streak\n`{streak}` consecutive day(s)",
                                }
                            ],
                            "accessory": {"type": 11, "media": {"url": str(target.display_avatar.url)}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"{bar}\n"
                                f"**Total dailies claimed** `{total}`\n"
                                f"{last_text}\n\n"
                                f"-# 🔥 x3 = +20% XP · 🔥 x7 = +50% XP"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="portfolio", description="Receive the build portfolio in DM (paginated).")
    async def portfolio(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            dm = await interaction.user.create_dm()
        except discord.Forbidden:
            await interaction.followup.send("❌ Enable your DMs first!", ephemeral=True)
            return

        credits_present: set[str] = {f["credit"] for f in PORTFOLIO_FILES if f["credit"]}
        collab_lines = []
        for key in credits_present:
            info  = CREDITS.get(key, {})
            label = info.get("label", key)
            url   = info.get("url")
            collab_lines.append(f"• [{label}]({url})" if url else f"• **{label}**")
        collab_text = "\n".join(collab_lines) if collab_lines else "Personal projects only."
        total_builds = len(PORTFOLIO_FILES)

        shuffled = random.sample(PORTFOLIO_FILES, len(PORTFOLIO_FILES))

        view = PortfolioView(
            entries=shuffled,
            author=interaction.user,
            total_builds=total_builds,
            collab_text=collab_text,
        )
        embed = view.build_embed()

        try:
            await dm.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send("❌ Enable your DMs first!", ephemeral=True)
            return

        await interaction.followup.send(
            "✓ Portfolio sent to your DMs (paginated with buttons)! 🍍", ephemeral=True
        )

    @app_commands.command(name="review", description="Leave a review for a commission.")
    async def review(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReviewStep1())

    @app_commands.command(name="inspirations", description="Get 3 random build inspirations.")
    async def inspirations(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        picks = random.sample(PORTFOLIO_FILES, min(3, len(PORTFOLIO_FILES)))
        accents = [0xA8D8EA, 0xF7CAC9, 0xC3B1E1]
        components = []
        for i, entry in enumerate(picks):
            img_url     = RELEASE_BASE + entry["name"]
            credit      = entry.get("credit")
            credit_info = CREDITS.get(credit) if credit else None
            caption     = "-# " + (f"Collaboration: {credit_info['label']}" if credit_info else "Personal build")
            components.append({
                "type": 17,
                "accent_color": accents[i % len(accents)],
                "components": [
                    {"type": 12, "items": [{"media": {"url": img_url}}]},
                    {"type": 10, "content": caption},
                ],
            })

        header = {
            "type": 17,
            "accent_color": 0x1E90FF,
            "components": [
                {
                    "type": 9,
                    "components": [
                        {"type": 10, "content": "## 🏗️ Build Inspirations\n3 random builds from the portfolio."}
                    ],
                    "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                }
            ],
        }
        await api_send(interaction.channel.id, {"flags": 32768, "components": [header] + components})
        await interaction.delete_original_response()

    @app_commands.command(name="price", description="Display the commission price list.")
    async def price(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFFD700,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": "# 💰 Commission Price List\nAll prices are indicative and may vary based on complexity."}
                            ],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                "### 🏗️ Builds\n"
                                "`Small` — House, shop, decoration · **5€ – 15€**\n"
                                "`Medium` — Spawn, arena, district · **15€ – 40€**\n"
                                "`Large` — Full map, city, megabuild · **40€ – 100€+**\n\n"
                                "### 🔌 Plugins / Mods\n"
                                "`Simple` — Config, small feature · **10€ – 25€**\n"
                                "`Advanced` — Full plugin/mod · **25€ – 80€+**\n\n"
                                "### ⚙️ Server Setup\n"
                                "`Basic` — Install + config · **15€ – 30€**\n"
                                "`Full` — Complete server setup · **30€ – 70€+**\n\n"
                                "### 📚 Formation / Coaching\n"
                                "`Session` — 1h coaching · **10€ – 20€**\n"
                                "`Pack` — 5h pack · **40€ – 80€**"
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "-# Open a 🎨 Commission ticket for a personalised quote. 🍍"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="faq", description="Frequently asked questions about commissions.")
    async def faq(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xA8D8EA,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": "# ❓ FAQ — Commissions\nMost common questions answered."}
                            ],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                "**How do I order?**\nOpen a 🎨 Commission ticket and fill in the form.\n\n"
                                "**How long does it take?**\nDepends on complexity. Usually 2–7 days. Deadline can be discussed.\n\n"
                                "**What payment methods are accepted?**\nPayPal, Lydia, or bank transfer. Payment after delivery for regulars.\n\n"
                                "**Can I see examples?**\nYes! Use `/portfolio` to receive a selection of builds in DM.\n\n"
                                "**Do you do revisions?**\nYes, minor revisions are included. Major changes may have a fee.\n\n"
                                "**Can I get a refund?**\nIf work hasn't started, yes. Once started, partial refund only.\n\n"
                                "**Do you work on any Minecraft version?**\nYes, Java and Bedrock, all major versions.\n\n"
                                "**Can I request a plugin for a specific server software?**\nSpigot, Paper, Fabric, Forge — all supported."
                            ),
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "-# Still have a question? Open a ❓ Question ticket! 🍍"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="availability", description="Check current availability for commissions.")
    async def availability(self, interaction: discord.Interaction):
        data   = db.config()
        status = data.get("availability", "available")
        status_map = {
            "available": ("🟢", "Available",  "Commissions are open! Feel free to open a ticket.", 0x57F287),
            "busy":      ("🟡", "Busy",        "Currently working on commissions. New orders may be delayed.", 0xFEE75C),
            "closed":    ("🔴", "Closed",      "Commissions are temporarily closed. Check back later.", 0xED4245),
        }
        emoji, label, desc, accent = status_map.get(status, status_map["available"])
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": accent,
                    "components": [
                        {
                            "type": 9,
                            "components": [{"type": 10, "content": f"## {emoji} {label}\n{desc}"}],
                            "accessory": {"type": 11, "media": {"url": LOGO_URL}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": "-# Open a 🎨 Commission ticket to discuss your project. 🍍"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="availability-set", description="Set your availability status.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Available — commissions open",    value="available"),
        app_commands.Choice(name="🟡 Busy — delays possible",          value="busy"),
        app_commands.Choice(name="🔴 Closed — not taking commissions", value="closed"),
    ])
    async def availability_set(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        data = db.config()
        data["availability"] = status.value
        db.save_config(data)
        await interaction.response.send_message(f"✓ Availability set to **{status.name}**.", ephemeral=True)

    @app_commands.command(name="snipe", description="Show the last deleted message in this channel.")
    async def snipe(self, interaction: discord.Interaction):
        from cogs.logs import _snipe_cache
        entry = _snipe_cache.get(interaction.channel.id)
        if not entry:
            await interaction.response.send_message("Nothing to snipe here.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xED4245,
                    "components": [
                        {
                            "type": 9,
                            "components": [{"type": 10, "content": "## 🎯 Sniped!\nLast deleted message in this channel."}],
                            "accessory": {"type": 11, "media": {"url": entry["avatar"]}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Author** {entry['author']}\n"
                                f"**Deleted** <t:{entry['ts']}:R>\n\n"
                                f"{entry['content'] or '*No text content*'}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="editsnipe", description="Show the last edited message in this channel.")
    async def editsnipe(self, interaction: discord.Interaction):
        from cogs.logs import _editsnipe_cache
        entry = _editsnipe_cache.get(interaction.channel.id)
        if not entry:
            await interaction.response.send_message("Nothing to edit-snipe here.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0xFEE75C,
                    "components": [
                        {
                            "type": 9,
                            "components": [{"type": 10, "content": "## ✏️ Edit Sniped!\nLast edited message in this channel."}],
                            "accessory": {"type": 11, "media": {"url": entry["avatar"]}},
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                f"**Author** {entry['author']}\n"
                                f"**Edited** <t:{entry['ts']}:R>\n\n"
                                f"**Before**\n{entry['before'] or '*empty*'}\n\n"
                                f"**After**\n{entry['after'] or '*empty*'}"
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))