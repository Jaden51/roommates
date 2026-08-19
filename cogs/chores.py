import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import GuildCommandsMixin
import db.database as db
from services.schedules import (
    WEEKDAYS,
    describe_schedule,
    next_occurrences,
)

FREQ_MAP = {
    "Weekly": "weekly",
    "Biweekly": "biweekly",
    "Monthly weekday": "monthly_nth",
    "Monthly day": "monthly_day",
}
WEEKDAY_MAP = {day: index for index, day in enumerate(WEEKDAYS)}
NTH_MAP = {"First": 1, "Second": 2, "Third": 3, "Fourth": 4, "Last": -1}
BIWEEKLY_MODE_MAP = {
    "Every 14 days": "every_14_days",
    "Every other weekday": "every_other_weekday",
}


class ChoresCog(GuildCommandsMixin, commands.Cog):
    """Recurring chore reminders."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    chore = app_commands.Group(name="chore", description="Manage recurring chore reminders.")

    async def _chore_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        conn = await db.connect()
        cursor = await conn.execute(
            "SELECT name FROM chores WHERE guild_id = ? ORDER BY name",
            (interaction.guild_id,),
        )
        names = [row["name"] for row in await cursor.fetchall()]
        return [
            app_commands.Choice(name=name, value=name)
            for name in names
            if current.lower() in name.lower()
        ][:25]

    @chore.command(name="create", description="Create a recurring chore reminder.")
    @app_commands.describe(
        name="Chore name, e.g. Change bedding",
        freq="How often it repeats",
        weekday="Weekday (for weekly / biweekly weekday / monthly weekday)",
        biweekly_mode="Biweekly mode (for biweekly)",
        start_date="Start date as YYYY-MM-DD (for biweekly)",
        nth="Which week of the month (for monthly weekday)",
        day_of_month="Day of the month, 1-31 (for monthly day)",
    )
    async def chore_create(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 50],
        freq: Literal["Weekly", "Biweekly", "Monthly weekday", "Monthly day"],
        weekday: Literal[
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        ] | None = None,
        biweekly_mode: Literal["Every 14 days", "Every other weekday"] | None = None,
        start_date: str | None = None,
        nth: Literal["First", "Second", "Third", "Fourth", "Last"] | None = None,
        day_of_month: app_commands.Range[int, 1, 31] | None = None,
    ):
        freq_raw = FREQ_MAP[freq]
        if freq_raw == "weekly":
            if (
                weekday is None
                or biweekly_mode is not None
                or start_date is not None
                or nth is not None
                or day_of_month is not None
            ):
                await interaction.response.send_message(
                    "For a weekly chore, provide only the weekday.", ephemeral=True
                )
                return
            dow, nth_v, dom, biweekly_mode_v, start_date_v = (
                WEEKDAY_MAP[weekday],
                None,
                None,
                None,
                None,
            )
        elif freq_raw == "biweekly":
            if biweekly_mode is None or start_date is None or nth is not None or day_of_month is not None:
                await interaction.response.send_message(
                    "For a biweekly chore, provide mode and start date. Use weekday only for the 'Every other weekday' mode.",
                    ephemeral=True,
                )
                return
            try:
                start_date_v = datetime.datetime.strptime(start_date, "%Y-%m-%d").date().isoformat()
            except ValueError:
                await interaction.response.send_message(
                    "Start date must be in YYYY-MM-DD format.", ephemeral=True
                )
                return

            biweekly_mode_v = BIWEEKLY_MODE_MAP[biweekly_mode]
            if biweekly_mode_v == "every_14_days":
                if weekday is not None:
                    await interaction.response.send_message(
                        "For biweekly 'Every 14 days', do not provide a weekday.",
                        ephemeral=True,
                    )
                    return
                dow = None
            else:
                if weekday is None:
                    await interaction.response.send_message(
                        "For biweekly 'Every other weekday', provide a weekday.",
                        ephemeral=True,
                    )
                    return
                dow = WEEKDAY_MAP[weekday]
            nth_v, dom = None, None
        elif freq_raw == "monthly_nth":
            if (
                weekday is None
                or biweekly_mode is not None
                or start_date is not None
                or nth is None
                or day_of_month is not None
            ):
                await interaction.response.send_message(
                    "For a monthly weekday chore, provide the weekday and which week.", ephemeral=True
                )
                return
            dow, nth_v, dom, biweekly_mode_v, start_date_v = (
                WEEKDAY_MAP[weekday],
                NTH_MAP[nth],
                None,
                None,
                None,
            )
        else:
            if (
                biweekly_mode is not None
                or start_date is not None
                or day_of_month is None
                or weekday is not None
                or nth is not None
            ):
                await interaction.response.send_message(
                    "For a monthly day chore, provide only the day of the month.", ephemeral=True
                )
                return
            dow, nth_v, dom, biweekly_mode_v, start_date_v = (
                None,
                None,
                day_of_month,
                None,
                None,
            )

        member_id = await self._register(interaction)
        conn = await db.connect()
        try:
            await conn.execute(
                """
                INSERT INTO chores
                (guild_id, name, created_by, freq, day_of_week, nth, day_of_month, biweekly_mode, start_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild_id,
                    name.strip(),
                    member_id,
                    freq_raw,
                    dow,
                    nth_v,
                    dom,
                    biweekly_mode_v,
                    start_date_v,
                ),
            )
            await conn.commit()
        except Exception:
            await interaction.response.send_message(
                f"A chore called `{name}` already exists.", ephemeral=True
            )
            return

        cursor = await conn.execute(
            "SELECT * FROM chores WHERE guild_id = ? AND name = ?",
            (interaction.guild_id, name),
        )
        row = await cursor.fetchone()
        await interaction.response.send_message(
            f"Created chore `{name}` — **{describe_schedule(row)}**.", ephemeral=True
        )

    @chore.command(name="list", description="List this server's chores and their schedules.")
    async def chore_list(self, interaction: discord.Interaction):
        await self._register(interaction)
        conn = await db.connect()
        cursor = await conn.execute(
            """
            SELECT ch.*, m.display_name
            FROM chores ch
            JOIN members m ON m.id = ch.created_by
            WHERE ch.guild_id = ?
            ORDER BY ch.name
            """,
            (interaction.guild_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            await interaction.response.send_message(
                "No chores yet. Use `/chore create` to add one.", ephemeral=True
            )
            return
        embed = discord.Embed(title="Chores", color=discord.Color.blurple())
        for row in rows:
            embed.add_field(
                name=row["name"],
                value=f"{describe_schedule(row)} · by {row['display_name']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chore.command(name="delete", description="Delete a chore.")
    @app_commands.autocomplete(name=_chore_autocomplete)
    async def chore_delete(self, interaction: discord.Interaction, name: str):
        await self._register(interaction)
        conn = await db.connect()
        cursor = await conn.execute(
            "DELETE FROM chores WHERE guild_id = ? AND name = ?",
            (interaction.guild_id, name),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            await interaction.response.send_message(
                f"No chore called `{name}`.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"Deleted chore `{name}`.", ephemeral=True)

    @chore.command(name="next", description="Show the next occurrences of a chore.")
    @app_commands.describe(name="Chore name", count="How many upcoming dates to show (1-10)")
    @app_commands.autocomplete(name=_chore_autocomplete)
    async def chore_next(
        self,
        interaction: discord.Interaction,
        name: str,
        count: app_commands.Range[int, 1, 10] = 5,
    ):
        await self._register(interaction)
        conn = await db.connect()
        cursor = await conn.execute(
            "SELECT * FROM chores WHERE guild_id = ? AND name = ?",
            (interaction.guild_id, name),
        )
        row = await cursor.fetchone()
        if row is None:
            await interaction.response.send_message(f"No chore called `{name}`.", ephemeral=True)
            return

        guild = await db.get_guild_config(interaction.guild_id)
        today = datetime.datetime.now(ZoneInfo(guild["timezone"])).date()
        dates = next_occurrences(row, today, count)
        embed = discord.Embed(
            title=name,
            description=describe_schedule(row),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Next occurrences",
            value="\n".join(d.strftime("%A, %B %d, %Y") for d in dates)
            or "No upcoming dates found in the next few months.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChoresCog(bot))
