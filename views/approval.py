import json

import discord

import db.database as db
from util import format_money

APPROVE_PREFIX = "expense_approve"
REJECT_PREFIX = "expense_reject"


async def fetch_expense(expense_id: int) -> dict | None:
    """Return the expense row plus its members and recorded votes."""
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT e.*, c.name AS category_name, m.display_name AS payer_name
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        JOIN members m ON m.id = e.payer_id
        WHERE e.id = ?
        """,
        (expense_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    cursor = await conn.execute(
        "SELECT id, display_name FROM members WHERE guild_id = ? ORDER BY display_name",
        (row["guild_id"],),
    )
    members = await cursor.fetchall()

    cursor = await conn.execute(
        """
        SELECT a.member_id, a.decision
        FROM expense_approvals a
        WHERE a.expense_id = ?
        """,
        (expense_id,),
    )
    votes = await cursor.fetchall()
    return {"expense": row, "members": members, "votes": votes}


def build_expense_embed(record: dict) -> discord.Embed:
    exp = record["expense"]
    if exp["status"] == "approved":
        color = discord.Color.green()
    elif exp["status"] == "rejected":
        color = discord.Color.red()
    else:
        color = discord.Color.blurple()

    embed = discord.Embed(
        title=f"{exp['category_name']} — {format_money(exp['amount_cents'])}",
        description=exp["note"] or None,
        color=color,
    )
    embed.add_field(name="Paid by", value=exp["payer_name"], inline=True)
    embed.add_field(name="Status", value=exp["status"].capitalize(), inline=True)

    required = json.loads(exp["required_voters"])
    by_id = {m["id"]: m["display_name"] for m in record["members"]}
    vote_by = {v["member_id"]: v["decision"] for v in record["votes"]}

    parts = []
    for member_id in required:
        name = by_id.get(member_id, "Unknown")
        decision = vote_by.get(member_id)
        mark = "✅" if decision == "approved" else "❌" if decision == "rejected" else "⏳"
        parts.append(f"{mark} {name}")

    embed.add_field(name="Approval", value="\n".join(parts) if parts else "No one else to approve.", inline=False)
    return embed


class ExpenseApprovalView(discord.ui.View):
    """Approve/Reject buttons for a pending expense."""

    def __init__(self, expense_id: int):
        super().__init__(timeout=None)
        self.expense_id = expense_id

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            custom_id=f"{APPROVE_PREFIX}:{expense_id}",
        )
        approve.callback = self._on_approve
        self.add_item(approve)

        reject = discord.ui.Button(
            label="Reject",
            style=discord.ButtonStyle.danger,
            custom_id=f"{REJECT_PREFIX}:{expense_id}",
        )
        reject.callback = self._on_reject
        self.add_item(reject)

    async def _on_approve(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "approved")

    async def _on_reject(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "rejected")

    async def _vote(self, interaction: discord.Interaction, decision: str) -> None:
        record = await fetch_expense(self.expense_id)
        if record is None:
            await interaction.response.send_message("This expense no longer exists.", ephemeral=True)
            return

        exp = record["expense"]
        conn = await db.connect()
        member_id = await db.ensure_member(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )

        if member_id == exp["payer_id"]:
            await interaction.response.send_message("You can't vote on your own expense.", ephemeral=True)
            return

        required = json.loads(exp["required_voters"])
        if member_id not in required:
            await interaction.response.send_message("You're not on the approval list for this expense.", ephemeral=True)
            return

        cursor = await conn.execute(
            "SELECT decision FROM expense_approvals WHERE expense_id = ? AND member_id = ?",
            (self.expense_id, member_id),
        )
        if await cursor.fetchone() is not None:
            await interaction.response.send_message("You've already voted on this expense.", ephemeral=True)
            return

        await conn.execute(
            "INSERT INTO expense_approvals (expense_id, member_id, decision) VALUES (?, ?, ?)",
            (self.expense_id, member_id, decision),
        )

        cursor = await conn.execute(
            "SELECT member_id, decision FROM expense_approvals WHERE expense_id = ?",
            (self.expense_id,),
        )
        votes = {r["member_id"]: r["decision"] for r in await cursor.fetchall()}

        completed = all(mid in votes for mid in required)
        if completed:
            status = "rejected" if any(votes.get(mid) == "rejected" for mid in required) else "approved"
            await conn.execute(
                "UPDATE expenses SET status = ? WHERE id = ?", (status, self.expense_id)
            )
            for item in self.children:
                item.disabled = True
        await conn.commit()

        record = await fetch_expense(self.expense_id)
        await interaction.response.send_message("Vote recorded.", ephemeral=True)
        if record is not None:
            await interaction.message.edit(embed=build_expense_embed(record), view=self)
