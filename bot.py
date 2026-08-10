import asyncio
import logging

import discord
from discord.ext import commands, tasks

import config
import db.database as db
from services.scheduler import run_daily_checks
from views.approval import ExpenseApprovalView
from views.split import SplitProposalView

logger = logging.getLogger(__name__)

COGS = [
    "cogs.setup",
    "cogs.expenses",
    "cogs.split",
    "cogs.chores",
    "cogs.statements",
]

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@tasks.loop(hours=1)
async def daily_scheduler() -> None:
    await run_daily_checks(bot)


@daily_scheduler.before_loop
async def _before_scheduler() -> None:
    await bot.wait_until_ready()


async def _register_persistent_views() -> None:
    """Re-bind buttons for pending expenses/proposals so they keep working after a restart."""
    conn = await db.connect()
    cursor = await conn.execute("SELECT id FROM expenses WHERE status = 'pending'")
    expense_ids = [row["id"] for row in await cursor.fetchall()]
    cursor = await conn.execute("SELECT id FROM split_proposals WHERE status = 'pending'")
    proposal_ids = [row["id"] for row in await cursor.fetchall()]
    for expense_id in expense_ids:
        bot.add_view(ExpenseApprovalView(expense_id))
    for proposal_id in proposal_ids:
        bot.add_view(SplitProposalView(proposal_id))
    logger.info(
        "Registered %d pending expense view(s) and %d pending proposal view(s)",
        len(expense_ids),
        len(proposal_ids),
    )


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id)
    for guild in bot.guilds:
        await db.ensure_guild(guild.id)
        await bot.tree.sync(guild=discord.Object(id=guild.id))
    logger.info("Synced commands for %d guild(s)", len(bot.guilds))
    if not daily_scheduler.is_running():
        daily_scheduler.start()


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    async with bot:
        await db.init_schema()
        for cog in COGS:
            await bot.load_extension(cog)
        await _register_persistent_views()
        await bot.start(config.BOT_TOKEN)
    await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
