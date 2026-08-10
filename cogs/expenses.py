import datetime
import json
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

import db.database as db
from util import format_money, to_cents
from views.approval import ExpenseApprovalView, build_expense_embed, fetch_expense


class ExpensesCog(commands.Cog):
    """Expense categories and shared-expense tracking with approval flow."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    category = app_commands.Group(name="category", description="Manage expense categories.")
    expense = app_commands.Group(name="expense", description="Track shared expenses.")

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

    @category.command(name="add", description="Create a new expense category.")
    @app_commands.describe(name="Category name, e.g. Groceries")
    async def category_add(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        if not name:
            await interaction.response.send_message("Category name can't be empty.", ephemeral=True)
            return
        member_id = await self._register(interaction)
        conn = await db.connect()
        try:
            await conn.execute(
                "INSERT INTO categories (guild_id, name, created_by) VALUES (?, ?, ?)",
                (interaction.guild_id, name, member_id),
            )
            await conn.commit()
        except Exception:
            await interaction.response.send_message(f"Category `{name}` already exists.", ephemeral=True)
            return
        await interaction.response.send_message(f"Created category `{name}`.", ephemeral=True)

    @category.command(name="list", description="List this server's expense categories.")
    async def category_list(self, interaction: discord.Interaction):
        await self._register(interaction)
        conn = await db.connect()
        cursor = await conn.execute(
            """
            SELECT c.name, m.display_name
            FROM categories c
            JOIN members m ON m.id = c.created_by
            WHERE c.guild_id = ?
            ORDER BY c.name
            """,
            (interaction.guild_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            await interaction.response.send_message(
                "No categories yet. Use `/category add` to create one.", ephemeral=True
            )
            return
        embed = discord.Embed(title="Categories", color=discord.Color.blurple())
        for row in rows:
            embed.add_field(name=row["name"], value=f"Created by {row['display_name']}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _category_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        conn = await db.connect()
        cursor = await conn.execute(
            "SELECT name FROM categories WHERE guild_id = ? ORDER BY name",
            (interaction.guild_id,),
        )
        names = [r["name"] for r in await cursor.fetchall()]
        return [
            app_commands.Choice(name=name, value=name)
            for name in names
            if current.lower() in name.lower()
        ][:25]

    @expense.command(name="add", description="Record an expense you paid. Others must approve it.")
    @app_commands.describe(
        category="Expense category",
        amount="Amount in dollars, e.g. 25.50",
        note="Optional note",
    )
    @app_commands.autocomplete(category=_category_autocomplete)
    async def expense_add(
        self,
        interaction: discord.Interaction,
        category: str,
        amount: float,
        note: str = "",
    ):
        try:
            cents = to_cents(amount)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await self._register(interaction)
        conn = await db.connect()
        cursor = await conn.execute(
            "SELECT id FROM categories WHERE guild_id = ? AND name = ?",
            (interaction.guild_id, category),
        )
        cat = await cursor.fetchone()
        if cat is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return

        member_id = await db.ensure_member(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )
        cursor = await conn.execute(
            "SELECT id FROM members WHERE guild_id = ? AND id != ?",
            (interaction.guild_id, member_id),
        )
        required = [row["id"] for row in await cursor.fetchall()]

        month_key = await self._month_key(interaction)
        status = "approved" if not required else "pending"
        cursor = await conn.execute(
            """
            INSERT INTO expenses (guild_id, category_id, payer_id, amount_cents, note, month_key, status, required_voters)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild_id,
                cat["id"],
                member_id,
                cents,
                note.strip(),
                month_key,
                status,
                json.dumps(required),
            ),
        )
        expense_id = cursor.lastrowid
        await conn.commit()

        if status == "approved":
            await interaction.response.send_message(
                f"Recorded {format_money(cents)} for `{category}`. No one else is in the server to approve.",
                ephemeral=True,
            )
            return

        channel = await self._channel(interaction)
        record = await fetch_expense(expense_id)
        message = await channel.send(embed=build_expense_embed(record), view=ExpenseApprovalView(expense_id))
        await conn.execute(
            "UPDATE expenses SET message_id = ? WHERE id = ?", (message.id, expense_id)
        )
        await conn.commit()
        await interaction.response.send_message(
            f"Expense posted to {channel.mention} — waiting for everyone else to approve.",
            ephemeral=True,
        )

    @expense.command(name="list", description="List expenses for a month.")
    @app_commands.describe(month="Month as YYYY-MM (default: current month)")
    async def expense_list(self, interaction: discord.Interaction, month: str | None = None):
        await self._register(interaction)
        if month is None:
            month = await self._month_key(interaction)
        try:
            datetime.datetime.strptime(month, "%Y-%m")
        except ValueError:
            await interaction.response.send_message("Month must be in YYYY-MM format.", ephemeral=True)
            return

        conn = await db.connect()
        cursor = await conn.execute(
            """
            SELECT e.amount_cents, e.note, e.status, c.name AS category_name, m.display_name AS payer_name
            FROM expenses e
            JOIN categories c ON c.id = e.category_id
            JOIN members m ON m.id = e.payer_id
            WHERE e.guild_id = ? AND e.month_key = ?
            ORDER BY e.created_at DESC
            """,
            (interaction.guild_id, month),
        )
        rows = await cursor.fetchall()
        if not rows:
            await interaction.response.send_message(f"No expenses for {month}.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Expenses — {month}", color=discord.Color.blurple())
        for row in rows[:15]:
            extra = f" · {row['note']}" if row["note"] else ""
            embed.add_field(
                name=f"{row['category_name']} — {format_money(row['amount_cents'])}",
                value=f"{row['payer_name']} · {row['status'].capitalize()}{extra}",
                inline=False,
            )
        if len(rows) > 15:
            embed.set_footer(text=f"…and {len(rows) - 15} more")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExpensesCog(bot))
