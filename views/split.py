import json

import discord

import db.database as db
from services.splits import set_global_config

APPROVE_PREFIX = "split_approve"
REJECT_PREFIX = "split_reject"


async def fetch_proposal(proposal_id: int) -> dict | None:
    """Return the proposal row plus its shares, members, and recorded votes."""
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT p.*, m.display_name AS proposer_name
        FROM split_proposals p
        JOIN members m ON m.id = p.proposed_by
        WHERE p.id = ?
        """,
        (proposal_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    cursor = await conn.execute(
        """
        SELECT s.member_id, s.share_percent, m.display_name
        FROM split_proposal_shares s
        JOIN members m ON m.id = s.member_id
        WHERE s.proposal_id = ?
        ORDER BY m.display_name
        """,
        (proposal_id,),
    )
    shares = await cursor.fetchall()

    cursor = await conn.execute(
        "SELECT id, display_name FROM members WHERE guild_id = ? ORDER BY display_name",
        (row["guild_id"],),
    )
    members = await cursor.fetchall()

    cursor = await conn.execute(
        "SELECT voter_id, decision FROM split_proposal_votes WHERE proposal_id = ?",
        (proposal_id,),
    )
    votes = await cursor.fetchall()
    return {"proposal": row, "shares": shares, "members": members, "votes": votes}


def build_proposal_embed(record: dict) -> discord.Embed:
    prop = record["proposal"]
    if prop["status"] == "approved":
        color = discord.Color.green()
    elif prop["status"] == "rejected":
        color = discord.Color.red()
    else:
        color = discord.Color.blurple()

    embed = discord.Embed(title="Proposed expense split change", color=color)
    embed.add_field(name="Proposed by", value=prop["proposer_name"], inline=True)
    embed.add_field(name="Status", value=prop["status"].capitalize(), inline=True)

    share_lines = [f"{s['display_name']} — {s['share_percent']:g}%" for s in record["shares"]]
    embed.add_field(name="New split", value="\n".join(share_lines), inline=False)

    required = json.loads(prop["required_voters"])
    by_id = {m["id"]: m["display_name"] for m in record["members"]}
    vote_by = {v["voter_id"]: v["decision"] for v in record["votes"]}

    parts = []
    for member_id in required:
        name = by_id.get(member_id, "Unknown")
        decision = vote_by.get(member_id)
        mark = "✅" if decision == "approved" else "❌" if decision == "rejected" else "⏳"
        parts.append(f"{mark} {name}")

    embed.add_field(name="Approval", value="\n".join(parts) if parts else "No one else to approve.", inline=False)
    return embed


class SplitProposalView(discord.ui.View):
    """Approve/Reject buttons for a pending split change."""

    def __init__(self, proposal_id: int):
        super().__init__(timeout=None)
        self.proposal_id = proposal_id

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            custom_id=f"{APPROVE_PREFIX}:{proposal_id}",
        )
        approve.callback = self._on_approve
        self.add_item(approve)

        reject = discord.ui.Button(
            label="Reject",
            style=discord.ButtonStyle.danger,
            custom_id=f"{REJECT_PREFIX}:{proposal_id}",
        )
        reject.callback = self._on_reject
        self.add_item(reject)

    async def _on_approve(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "approved")

    async def _on_reject(self, interaction: discord.Interaction) -> None:
        await self._vote(interaction, "rejected")

    async def _vote(self, interaction: discord.Interaction, decision: str) -> None:
        record = await fetch_proposal(self.proposal_id)
        if record is None:
            await interaction.response.send_message("This proposal no longer exists.", ephemeral=True)
            return

        prop = record["proposal"]
        conn = await db.connect()
        member_id = await db.ensure_member(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )

        if member_id == prop["proposed_by"]:
            await interaction.response.send_message("You can't vote on your own proposal.", ephemeral=True)
            return

        required = json.loads(prop["required_voters"])
        if member_id not in required:
            await interaction.response.send_message("You're not on the approval list for this proposal.", ephemeral=True)
            return

        cursor = await conn.execute(
            "SELECT decision FROM split_proposal_votes WHERE proposal_id = ? AND voter_id = ?",
            (self.proposal_id, member_id),
        )
        if await cursor.fetchone() is not None:
            await interaction.response.send_message("You've already voted on this proposal.", ephemeral=True)
            return

        await conn.execute(
            "INSERT INTO split_proposal_votes (proposal_id, voter_id, decision) VALUES (?, ?, ?)",
            (self.proposal_id, member_id, decision),
        )

        cursor = await conn.execute(
            "SELECT voter_id, decision FROM split_proposal_votes WHERE proposal_id = ?",
            (self.proposal_id,),
        )
        votes = {r["voter_id"]: r["decision"] for r in await cursor.fetchall()}

        completed = all(mid in votes for mid in required)
        approved_config_id: int | None = None
        if completed:
            rejected = any(votes.get(mid) == "rejected" for mid in required)
            if rejected:
                await conn.execute(
                    "UPDATE split_proposals SET status = 'rejected' WHERE id = ?",
                    (self.proposal_id,),
                )
            else:
                cursor = await conn.execute(
                    "INSERT INTO split_configs (guild_id, changed_by) VALUES (?, ?)",
                    (prop["guild_id"], prop["proposed_by"]),
                )
                config_id = cursor.lastrowid
                for share in record["shares"]:
                    await conn.execute(
                        "INSERT INTO split_shares (config_id, member_id, share_percent) VALUES (?, ?, ?)",
                        (config_id, share["member_id"], share["share_percent"]),
                    )
                await conn.execute(
                    "UPDATE split_proposals SET status = 'approved', config_id = ? WHERE id = ?",
                    (config_id, self.proposal_id),
                )
                approved_config_id = config_id
            for item in self.children:
                item.disabled = True
        await conn.commit()
        if approved_config_id is not None:
            await set_global_config(prop["guild_id"], approved_config_id)

        record = await fetch_proposal(self.proposal_id)
        await interaction.response.send_message("Vote recorded.", ephemeral=True)
        if record is not None:
            await interaction.message.edit(embed=build_proposal_embed(record), view=self)
