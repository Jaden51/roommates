import datetime
import logging
from zoneinfo import ZoneInfo

import discord

import config
import db.database as db
from services.posting import get_announce_channel
from services.schedules import due_chores
from services.settlement import build_statement_embed, compute_settlement

logger = logging.getLogger(__name__)


def _reminder_time() -> datetime.time:
    return datetime.time(config.DEFAULT_REMINDER_HOUR, config.DEFAULT_REMINDER_MINUTE)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).day


async def run_daily_checks(bot: discord.Client) -> None:
    """Check every guild for due chores and month-end statements."""
    conn = await db.connect()
    cursor = await conn.execute("SELECT guild_id FROM guilds")
    guild_ids = [row["guild_id"] for row in await cursor.fetchall()]

    for guild_id in guild_ids:
        try:
            await _check_guild(bot, guild_id)
        except Exception:
            logger.exception("Error running daily checks for guild %s", guild_id)


async def _check_guild(bot: discord.Client, guild_id: int) -> None:
    guild = await db.get_guild_config(guild_id)
    now = datetime.datetime.now(ZoneInfo(guild["timezone"]))
    if now.time() < _reminder_time():
        return

    channel = await get_announce_channel(bot, guild_id)
    if channel is None:
        return

    today = now.date()
    await _post_chore_reminders(guild_id, channel, today)
    if today.day == _last_day_of_month(today.year, today.month):
        await _post_monthly_statement(guild_id, channel, today)


async def _post_chore_reminders(guild_id: int, channel: discord.abc.Messageable, today: datetime.date) -> None:
    due = await due_chores(guild_id, today)
    if not due:
        return

    conn = await db.connect()
    to_post = []
    for chore in due:
        cursor = await conn.execute(
            "SELECT 1 FROM chore_occurrences WHERE chore_id = ? AND due_date = ?",
            (chore["id"], today.isoformat()),
        )
        if await cursor.fetchone() is None:
            await conn.execute(
                "INSERT INTO chore_occurrences (chore_id, due_date) VALUES (?, ?)",
                (chore["id"], today.isoformat()),
            )
            to_post.append(chore)
    await conn.commit()
    if not to_post:
        return

    embed = discord.Embed(title="Chores due today", color=discord.Color.blurple())
    embed.add_field(
        name=today.strftime("%A, %B %d"),
        value="\n".join(f"• {chore['name']}" for chore in to_post),
        inline=False,
    )
    await channel.send(embed=embed)


async def _post_monthly_statement(guild_id: int, channel: discord.abc.Messageable, today: datetime.date) -> None:
    month_key = today.strftime("%Y-%m")
    conn = await db.connect()
    cursor = await conn.execute(
        "SELECT 1 FROM posted_statements WHERE guild_id = ? AND month_key = ?",
        (guild_id, month_key),
    )
    if await cursor.fetchone() is not None:
        return

    data = await compute_settlement(guild_id, month_key)
    if data is None:
        await conn.execute(
            "INSERT INTO posted_statements (guild_id, month_key) VALUES (?, ?)",
            (guild_id, month_key),
        )
        await conn.commit()
        return

    await channel.send(embed=build_statement_embed(data))
    await conn.execute(
        "INSERT INTO posted_statements (guild_id, month_key) VALUES (?, ?)",
        (guild_id, month_key),
    )
    await conn.commit()
