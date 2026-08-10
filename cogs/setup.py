from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

import config
import db.database as db


class SetupCog(commands.Cog):
    """Server-level configuration for the bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    setup = app_commands.Group(
        name="setup",
        description="Configure how the bot behaves in this server.",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def _register(self, interaction: discord.Interaction) -> int:
        return await db.ensure_member(
            interaction.guild_id,
            interaction.user.id,
            interaction.user.display_name,
        )

    @setup.command(name="channel", description="Set the channel where reminders and statements are posted.")
    @app_commands.describe(channel="The channel to use for reminders and monthly statements.")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if channel.guild_id != interaction.guild_id:
            await interaction.response.send_message("That channel isn't in this server.", ephemeral=True)
            return
        await self._register(interaction)
        conn = await db.connect()
        await conn.execute(
            "UPDATE guilds SET channel_id = ? WHERE guild_id = ?",
            (channel.id, interaction.guild_id),
        )
        await conn.commit()
        await interaction.response.send_message(
            f"Reminders and statements will be posted in {channel.mention}.",
            ephemeral=True,
        )

    @setup.command(name="timezone", description="Set this server's timezone (IANA name, e.g. America/New_York).")
    @app_commands.describe(timezone="IANA timezone name, e.g. America/New_York or UTC")
    async def set_timezone(self, interaction: discord.Interaction, timezone: str):
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            await interaction.response.send_message(
                f"`{timezone}` isn't a valid IANA timezone name.", ephemeral=True
            )
            return
        await self._register(interaction)
        conn = await db.connect()
        await conn.execute(
            "UPDATE guilds SET timezone = ? WHERE guild_id = ?",
            (timezone, interaction.guild_id),
        )
        await conn.commit()
        await interaction.response.send_message(
            f"Server timezone set to `{timezone}`.", ephemeral=True
        )

    @setup.command(name="show", description="Show this server's bot configuration.")
    async def show(self, interaction: discord.Interaction):
        await self._register(interaction)
        guild = await db.get_guild_config(interaction.guild_id)
        channel = interaction.guild.get_channel(guild["channel_id"]) if guild["channel_id"] else None
        embed = discord.Embed(title="Server configuration", color=discord.Color.blurple())
        embed.add_field(
            name="Channel",
            value=channel.mention if channel else "Not set",
            inline=True,
        )
        embed.add_field(name="Timezone", value=guild["timezone"], inline=True)
        embed.add_field(
            name="Reminder time",
            value=f"{config.DEFAULT_REMINDER_HOUR:02d}:{config.DEFAULT_REMINDER_MINUTE:02d}",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup.error
    async def on_setup_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to use this command.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
