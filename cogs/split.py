import json

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import GuildCommandsMixin
import db.database as db
from services.splits import get_active_config, get_shares
from views.split import SplitProposalView, build_proposal_embed, fetch_proposal

MAX_MEMBERS = 3


class SplitCog(GuildCommandsMixin, commands.Cog):
    """Global expense split configuration, changeable with all-members approval."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    split = app_commands.Group(name="split", description="Manage how expenses are shared.")

    @split.command(name="get", description="Show the current expense split.")
    async def split_get(self, interaction: discord.Interaction):
        await self._register(interaction)
        config = await get_active_config(interaction.guild_id)
        if config is None:
            await interaction.response.send_message(
                "No custom split set yet — expenses are shared equally by default. "
                "Use `/split set` to propose a new split.",
                ephemeral=True,
            )
            return

        shares = await get_shares(config["id"])
        embed = discord.Embed(title="Current split", color=discord.Color.blurple())
        for share in shares:
            embed.add_field(
                name=share["display_name"],
                value=f"{share['share_percent']:g}%",
                inline=True,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @split.command(name="set", description="Propose a new split. Everyone must approve it.")
    @app_commands.describe(
        member1="First member",
        percent1="Their share, e.g. 50",
        member2="Second member",
        percent2="Their share, e.g. 30",
        member3="Third member",
        percent3="Their share, e.g. 20",
    )
    async def split_set(
        self,
        interaction: discord.Interaction,
        member1: discord.User,
        percent1: float,
        member2: discord.User | None = None,
        percent2: float | None = None,
        member3: discord.User | None = None,
        percent3: float | None = None,
    ):
        proposer_id = await self._register(interaction)

        pairs = [(member1, percent1)]
        for member, percent in ((member2, percent2), (member3, percent3)):
            if (member is None) != (percent is None):
                await interaction.response.send_message(
                    "Each member must come with a percentage.", ephemeral=True
                )
                return
            if member is not None:
                pairs.append((member, percent))

        if len({user.id for user, _ in pairs}) != len(pairs):
            await interaction.response.send_message("Each member can only appear once.", ephemeral=True)
            return

        total = sum(percent for _, percent in pairs)
        if any(percent <= 0 for _, percent in pairs) or abs(total - 100) > 0.005:
            await interaction.response.send_message(
                "Percentages must be positive and add up to 100.", ephemeral=True
            )
            return

        if len(pairs) > MAX_MEMBERS:
            await interaction.response.send_message(
                f"Only up to {MAX_MEMBERS} members are supported in one command. "
                "This is a limitation of Discord slash commands.",
                ephemeral=True,
            )
            return

        for user, _ in pairs:
            if interaction.guild.get_member(user.id) is None:
                await interaction.response.send_message(
                    f"{user.mention} isn't in this server.", ephemeral=True
                )
                return

        conn = await db.connect()

        share_by_member = {}
        for user, percent in pairs:
            member_id = await db.ensure_member(
                interaction.guild_id, user.id, user.display_name
            )
            share_by_member[member_id] = percent

        cursor = await conn.execute(
            "SELECT id FROM members WHERE guild_id = ?", (interaction.guild_id,)
        )
        registered = {row["id"] for row in await cursor.fetchall()}
        missing = registered - set(share_by_member)
        if missing:
            placeholders = ",".join("?" * len(missing))
            cursor = await conn.execute(
                f"SELECT display_name FROM members WHERE id IN ({placeholders})",
                tuple(missing),
            )
            names = ", ".join(row["display_name"] for row in await cursor.fetchall())
            await interaction.response.send_message(
                f"The split must include everyone: {names}. "
                "Use `/split get` to see the members.",
                ephemeral=True,
            )
            return

        cursor = await conn.execute(
            "SELECT id FROM members WHERE guild_id = ? AND id != ?",
            (interaction.guild_id, proposer_id),
        )
        required = [row["id"] for row in await cursor.fetchall()]

        cursor = await conn.execute(
            """
            INSERT INTO split_proposals (guild_id, proposed_by, status, required_voters)
            VALUES (?, ?, 'pending', ?)
            """,
            (interaction.guild_id, proposer_id, json.dumps(required)),
        )
        proposal_id = cursor.lastrowid
        for member_id, percent in share_by_member.items():
            await conn.execute(
                "INSERT INTO split_proposal_shares (proposal_id, member_id, share_percent) VALUES (?, ?, ?)",
                (proposal_id, member_id, percent),
            )
        await conn.commit()

        if not required:
            cursor = await conn.execute(
                "INSERT INTO split_configs (guild_id, changed_by) VALUES (?, ?)",
                (interaction.guild_id, proposer_id),
            )
            config_id = cursor.lastrowid
            for member_id, percent in share_by_member.items():
                await conn.execute(
                    "INSERT INTO split_shares (config_id, member_id, share_percent) VALUES (?, ?, ?)",
                    (config_id, member_id, percent),
                )
            await conn.execute(
                "UPDATE split_proposals SET status = 'approved', config_id = ? WHERE id = ?",
                (config_id, proposal_id),
            )
            await conn.commit()
            await interaction.response.send_message(
                "Split set — no one else is in the server to approve.", ephemeral=True
            )
            return

        channel = await self._channel(interaction)
        record = await fetch_proposal(proposal_id)
        await channel.send(
            embed=build_proposal_embed(record), view=SplitProposalView(proposal_id)
        )
        await interaction.response.send_message(
            f"Proposal posted to {channel.mention} — waiting for everyone else to approve.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SplitCog(bot))
