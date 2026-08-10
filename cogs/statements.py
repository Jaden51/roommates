import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import GuildCommandsMixin
from services.settlement import build_statement_embed, compute_settlement


class StatementsCog(GuildCommandsMixin, commands.Cog):
    """Monthly expense statements and settlements."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    statement = app_commands.Group(name="statement", description="Monthly expense statements.")

    @statement.command(name="show", description="Post the monthly settlement for who owes whom.")
    @app_commands.describe(month="Month as YYYY-MM (default: current month)")
    async def statement_show(self, interaction: discord.Interaction, month: str | None = None):
        await self._register(interaction)
        if month is None:
            month = await self._month_key(interaction)
        assert month is not None
        try:
            datetime.datetime.strptime(month, "%Y-%m")
        except ValueError:
            await interaction.response.send_message(
                "Month must be in YYYY-MM format.", ephemeral=True
            )
            return

        data = await compute_settlement(interaction.guild_id, month)
        if data is None:
            await interaction.response.send_message(
                f"No approved expenses for {month}.", ephemeral=True
            )
            return

        channel = await self._channel(interaction)
        await channel.send(embed=build_statement_embed(data))
        await interaction.response.send_message(
            f"Statement for {month} posted to {channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatementsCog(bot))
