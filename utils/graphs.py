"""Matplotlib-based charts (XP history over the last 7 days)."""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

import matplotlib

matplotlib.use("Agg")  # headless rendering
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

log = logging.getLogger(__name__)

_PALETTE = ["#5ECFFF", "#FFD166", "#8DA1AD", "#B8A0D0", "#C8F0C8", "#FFB3BA", "#A0D8EF"]


def _clean_axes(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#1e293b")
    ax.tick_params(colors="#64748b", labelsize=9)
    ax.grid(axis="y", color="#1e293b", linewidth=0.7)
    ax.set_axisbelow(True)


def generate_xp_graph(
    *,
    username: str,
    daily_xp: dict[str, int],
    days: int = 7,
) -> bytes:
    """Render a 7-day XP bar/line chart and return PNG bytes.

    ``daily_xp`` maps ISO dates (``YYYY-MM-DD``) to XP earned that day.
    """
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=d) for d in range(days - 1, -1, -1)]
    labels = [d.strftime("%Y-%m-%d") for d in dates]
    values = [int(daily_xp.get(lbl, 0)) for lbl in labels]

    fig, ax = plt.subplots(figsize=(6.6, 2.6), dpi=140)
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    colors = [_PALETTE[i % len(_PALETTE)] for i in range(days)]
    ax.bar(range(days), values, color=colors, width=0.62, zorder=3)
    ax.set_xticks(range(days))
    ax.set_xticklabels([d.strftime("%a") for d in dates])
    _clean_axes(ax)

    ax.set_title(f"XP — {username} (last {days} days)", color="#e2e8f0", fontsize=11, pad=10)
    for i, v in enumerate(values):
        if v:
            ax.text(i, v + max(values) * 0.02, str(v), ha="center", color="#cbd5e1", fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
