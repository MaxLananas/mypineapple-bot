"""Centralized, per-guild configurable settings.

All Discord IDs and tuning knobs live in :mod:`config` (single source of truth).
This module adds **per-guild overrides** stored in the ``config`` DB store under
``overrides``. A call like ``get(guild_id, "welcome_channel_id")`` returns the
guild override if set, otherwise the ``config.py`` default.

Usage::

    from utils import settings
    channel_id = settings.get(interaction.guild_id, "welcome_channel_id")
"""
from __future__ import annotations

import logging
from typing import Any

import config as _cfg

log = logging.getLogger(__name__)

# Registry of every guild-configurable setting and its default (from config.py).
DEFAULTS: dict[str, Any] = {
    "welcome_channel_id":  _cfg.WELCOME_CHANNEL_ID,
    "ticket_category_id":  _cfg.TICKET_CATEGORY_ID,
    "ticket_log_channel":  _cfg.TICKET_LOG_CHANNEL_ID,
    "log_hub_channel_id":  _cfg.LOG_HUB_CHANNEL_ID,
    "no_xp_channel_id":    _cfg.NO_XP_CHANNEL_ID,
    "no_xp_role_id":       _cfg.NO_XP_ROLE_ID,
    "booster_role_id":     _cfg.BOOSTER_ROLE_ID,
    "autorole_id":         _cfg.AUTOROLE_ID,
    "support_role_id":     _cfg.SUPPORT_ROLE_ID,
    "client_role_id":      _cfg.CLIENT_ROLE_ID,
    # Anti-spam tuning.
    "antispam_enabled":    True,
    "antispam_threshold":  4,      # identical messages within the window
    "antispam_window":     6.0,    # seconds
    "antispam_rapid":      6,      # messages within the rapid window
    "antispam_rapid_window": 3.0,  # seconds
}


def _overrides() -> dict:
    import utils.db as db
    return db.config().get("overrides", {})


def get(guild_id: int | None, key: str) -> Any:
    """Return the effective value for ``key`` (guild override or default)."""
    if guild_id is not None:
        ov = _overrides().get(str(guild_id), {})
        if key in ov:
            return ov[key]
    return DEFAULTS.get(key)


def set(guild_id: int, key: str, value: Any) -> None:
    """Store a per-guild override."""
    import utils.db as db
    cfg = db.config()
    ov = cfg.setdefault("overrides", {})
    ov.setdefault(str(guild_id), {})[key] = value
    db.save_config(cfg)
    log.info("Setting override %s=%s for guild %s", key, value, guild_id)


def reset(guild_id: int, key: str) -> None:
    """Remove a per-guild override (fall back to default)."""
    import utils.db as db
    cfg = db.config()
    ov = cfg.get("overrides", {})
    g = ov.get(str(guild_id), {})
    if key in g:
        del g[key]
        if not g:
            ov.pop(str(guild_id), None)
        db.save_config(cfg)
