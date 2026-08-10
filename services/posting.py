import discord

import db.database as db


async def get_announce_channel(bot: discord.Client, guild_id: int) -> discord.abc.Messageable | None:
    """Return the guild's configured announcement channel, if reachable."""
    guild = await db.get_guild_config(guild_id)
    if not guild["channel_id"]:
        return None
    guild_obj = bot.get_guild(guild_id)
    if guild_obj is None:
        return None
    channel = guild_obj.get_channel(guild["channel_id"])
    return channel if isinstance(channel, discord.abc.Messageable) else None
