"""Secret invite tracking.

Silently tracks who invited whom (no public announcements) and grants a small,
quiet XP reward to the inviter. The mapping is persisted so it survives restarts.
"""
from __future__ import annotations
import logging

import discord
from discord.ext import commands

import utils.db as db
from utils.leveling import add_xp

log = logging.getLogger(__name__)

INVITE_XP_REWARD = 30  # quiet reward for bringing someone in


class Invites(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # code -> uses snapshot, cached on ready.
        self._invites: dict[str, int] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                self._invites.update(
                    {inv.code: inv.uses for inv in await guild.invites()}
                )
            except discord.Forbidden:
                log.warning("Missing permission to read invites in %s", guild.name)
            except Exception as e:
                log.error("invite cache (%s): %s", guild.name, e)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild and invite.code:
            self._invites[invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self._invites.pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        inviter = None
        try:
            fresh = {inv.code: inv.uses for inv in await guild.invites()}
        except Exception:
            return

        for code, uses in fresh.items():
            if code in self._invites and uses > self._invites[code]:
                inviter = await self._find_inviter(guild, code)
                break
        self._invites = fresh

        if inviter is None or inviter.id == member.id:
            return

        # Persist the mapping (secret — never announced).
        data = db.config()
        invites = data.setdefault("invites", {})
        invites.setdefault(str(guild.id), {})[str(member.id)] = {
            "inviter_id": inviter.id,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        }
        db.save_config(data)

        # Quiet reward for the inviter.
        try:
            await add_xp(guild=guild, member=inviter, amount=INVITE_XP_REWARD)
        except Exception as e:
            log.error("invite reward: %s", e)

    async def _find_inviter(self, guild: discord.Guild, code: str):
        try:
            for inv in await guild.invites():
                if inv.code == code:
                    return inv.inviter
        except Exception:
            pass
        return None

    def inviter_of(self, guild_id: int, user_id: int):
        """Return the inviter's user id for a member, if known."""
        invites = db.config().get("invites", {})
        rec = invites.get(str(guild_id), {}).get(str(user_id))
        return rec.get("inviter_id") if rec else None


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
