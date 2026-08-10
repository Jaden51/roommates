import datetime
from zoneinfo import ZoneInfo

import discord

import db.database as db


class GuildCommandsMixin:
    """Shared helpers for guild-scoped cogs."""

    async def _register(self, interaction: discord.Interaction) -> int:
        return await db.ensure_member(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )

    async def _channel(self, interaction: discord.Interaction) -> discord.abc.Messageable:
        guild = await db.get_guild_config(interaction.guild_id)
        if guild["channel_id"]:
            channel = interaction.guild.get_channel(guild["channel_id"])
            if channel is not None:
                return channel
        return interaction.channel

    async def _month_key(self, interaction: discord.Interaction) -> str:
        guild = await db.get_guild_config(interaction.guild_id)
        now = datetime.datetime.now(ZoneInfo(guild["timezone"]))
        return now.strftime("%Y-%m")
