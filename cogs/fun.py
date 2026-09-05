from __future__ import annotations
import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.api import api_send, api_edit
from utils.helpers import ts_now

log = logging.getLogger(__name__)

EIGHTBALL_ANSWERS = [
    ("🟢", "Yes, absolutely — and I hope you didn't bet against it."),
    ("🟢", "The stars say yes… or was that the weather? Either way, yes."),
    ("🟢", "Of course! Well, 73.6% sure according to my rough calculations."),
    ("🟢", "Definitely. I'd stake my internet connection on it."),
    ("🟢", "Looks positive — like your karma if you stop spamming tickets."),
    ("🟡", "Maybe… I tried to see the future but it was down for maintenance."),
    ("🟡", "Ask again. My crystal ball is lagging."),
    ("🟡", "Unclear. Try rephrasing — or bring offerings."),
    ("🟡", "Cannot say right now. I'm in a meeting with my cat."),
    ("🟡", "Focus and ask again. And please, no silly questions."),
    ("🔴", "No. And it's not me saying it — it's the universe."),
    ("🔴", "Not at all. Not even close. Missed."),
    ("🔴", "My highly reliable quantum brain says: absolutely not."),
    ("🔴", "Pour yourself some water, because the answer is nope."),
    ("🔴", "The answer is no. You may cry. I'll understand."),
    ("🔴", "Outlook not great, like the weather on a random Tuesday."),
    ("💀", "Why are you asking me this? Who told you I know things?"),
    ("💀", "I refuse to answer for legal reasons."),
    ("💀", "This question killed me. I'm dead. Thank you."),
    ("💀", "According to my analysis, your question is the real disaster here."),
]

COINFLIP_SIDES = [
    ("HEADS", "🌊", 0xA8D8EA),
    ("TAILS", "🪙", 0xF7CAC9),
]

_poll_state: dict[str, dict] = {}

POLL_EMOJIS  = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
POLL_COLOURS = [
    discord.ButtonStyle.primary,
    discord.ButtonStyle.success,
    discord.ButtonStyle.danger,
    discord.ButtonStyle.secondary,
    discord.ButtonStyle.primary,
]


def _build_poll_text(question: str, options: list[str], counts: list[int], ts: int, multi: bool) -> str:
    total = sum(counts)
    lines = [f"## 📊 {question}\n"]
    for i, (opt, count) in enumerate(zip(options, counts)):
        pct    = int((count / total) * 100) if total else 0
        filled = int(pct / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        lines.append(f"{POLL_EMOJIS[i]} **{opt}** — `{bar}` {pct}% ({count} vote{'s' if count != 1 else ''})")
    mode = "Multi-choice" if multi else "Single choice"
    lines.append(f"\n-# {total} vote{'s' if total != 1 else ''} · {mode} · <t:{ts}:R>")
    return "\n".join(lines)


class PollButton(discord.ui.Button):
    def __init__(self, index: int, option: str, poll_key: str):
        super().__init__(
            label=option[:80],
            style=POLL_COLOURS[index % len(POLL_COLOURS)],
            emoji=POLL_EMOJIS[index],
            custom_id=f"poll_{poll_key}_{index}",
        )
        self.index    = index
        self.poll_key = poll_key

    async def callback(self, interaction: discord.Interaction):
        state = _poll_state.get(self.poll_key)
        if not state:
            await interaction.response.send_message("Poll expired.", ephemeral=True)
            return

        uid    = interaction.user.id
        counts = state["counts"]
        votes  = state["votes"]
        multi  = state["multi"]

        if multi:
            voted = votes.get(uid, set())
            if self.index in voted:
                voted.discard(self.index)
                counts[self.index] = max(0, counts[self.index] - 1)
                action = f"Removed vote from **{state['options'][self.index]}**"
            else:
                voted.add(self.index)
                counts[self.index] += 1
                action = f"Voted for **{state['options'][self.index]}**"
            votes[uid] = voted
        else:
            old = votes.get(uid)
            if old == self.index:
                await interaction.response.send_message(
                    f"You already voted for **{state['options'][self.index]}**!", ephemeral=True
                )
                return
            if old is not None:
                counts[old] = max(0, counts[old] - 1)
            votes[uid]          = self.index
            counts[self.index] += 1
            action = f"Voted for **{state['options'][self.index]}**"

        new_text = _build_poll_text(
            state["question"], state["options"], counts, state["ts"], multi
        )
        await interaction.response.edit_message(
            content=new_text,
            view=self.view,
        )


class PollView(discord.ui.View):
    def __init__(self, poll_key: str, options: list[str], multi: bool):
        super().__init__(timeout=3600)
        self.poll_key = poll_key
        for i, opt in enumerate(options):
            self.add_item(PollButton(i, opt, poll_key))

    async def on_timeout(self):
        _poll_state.pop(self.poll_key, None)


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="8ball", description="Ask the magic ball a question.")
    @app_commands.describe(question="Your question.")
    async def eightball(self, interaction: discord.Interaction, question: str):
        colour, answer = random.choice(EIGHTBALL_ANSWERS)
        await interaction.response.defer(ephemeral=True)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x9B8EC4,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {"type": 10, "content": f"## 🎱 Magic Ball\n*« {question} »*"}
                            ],
                            "accessory": {
                                "type": 11,
                                "media": {"url": str(interaction.user.display_avatar.url)},
                            },
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": f"{colour} **{answer}**"},
                        {"type": 14, "divider": True, "spacing": 1},
                        {"type": 10, "content": f"-# Asked by {interaction.user.mention}"},
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="coinflip", description="Flip a coin.")
    async def coinflip(self, interaction: discord.Interaction):
        result, emoji, accent = random.choice(COINFLIP_SIDES)
        await interaction.response.defer(ephemeral=True)

        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": 0x888888,
                    "components": [
                        {"type": 10, "content": "## 🪙 The coin is spinning…\n*🌀 Hold on…*"},
                    ],
                }
            ],
        })
        await asyncio.sleep(1.5)
        await api_send(interaction.channel.id, {
            "flags": 32768,
            "components": [
                {
                    "type": 17,
                    "accent_color": accent,
                    "components": [
                        {
                            "type": 9,
                            "components": [
                                {
                                    "type": 10,
                                    "content": (
                                        f"## {emoji} {result}!\n"
                                        f"{interaction.user.mention} flipped a coin."
                                    ),
                                }
                            ],
                            "accessory": {
                                "type": 11,
                                "media": {"url": str(interaction.user.display_avatar.url)},
                            },
                        },
                        {"type": 14, "divider": True, "spacing": 1},
                        {
                            "type": 10,
                            "content": (
                                "🌊 **HEADS** — blue, mysterious, like the ocean."
                                if result == "HEADS"
                                else "🪙 **TAILS** — silver, classic, reliable."
                            ),
                        },
                    ],
                }
            ],
        })
        await interaction.delete_original_response()

    @app_commands.command(name="poll", description="Create an interactive poll.")
    @app_commands.describe(
        question="The poll question.",
        option1="Option 1.",
        option2="Option 2.",
        option3="Option 3 (optional).",
        option4="Option 4 (optional).",
        option5="Option 5 (optional).",
        multi="Allow multiple choices? (default: no)",
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question:    str,
        option1:     str,
        option2:     str,
        option3:     str | None = None,
        option4:     str | None = None,
        option5:     str | None = None,
        multi:       bool = False,
    ):
        options = [o for o in [option1, option2, option3, option4, option5] if o]
        if len(options) < 2:
            await interaction.response.send_message("At least 2 options required.", ephemeral=True)
            return

        ts       = ts_now()
        poll_key = f"{interaction.id}"

        _poll_state[poll_key] = {
            "question": question,
            "options":  options,
            "counts":   [0] * len(options),
            "votes":    {},
            "ts":       ts,
            "multi":    multi,
        }

        text = _build_poll_text(question, options, [0] * len(options), ts, multi)
        view = PollView(poll_key, options, multi)

        await interaction.response.send_message(content=text, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))