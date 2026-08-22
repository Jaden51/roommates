import json

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import GuildCommandsMixin
import db.database as db
from services.splits import (
    clear_category_config,
    clear_global_config,
    create_config,
    get_active_category_config,
    get_active_global_config,
    get_shares,
    set_category_config,
    set_global_config,
    validate_percentages,
    validate_weights,
)
from views.split import SplitProposalView, build_proposal_embed, fetch_proposal

MAX_MEMBERS = 3


class SplitCog(GuildCommandsMixin, commands.Cog):
    """Global expense split configuration, changeable with all-members approval."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    split = app_commands.Group(name="split", description="Manage how expenses are shared.")
    split_category = app_commands.Group(
        name="category", description="Manage category-specific split overrides.", parent=split
    )

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

    async def _category_id(self, guild_id: int, name: str) -> int | None:
        conn = await db.connect()
        cursor = await conn.execute(
            "SELECT id FROM categories WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        row = await cursor.fetchone()
        return None if row is None else row["id"]

    async def _member_values(
        self,
        interaction: discord.Interaction,
        member1: discord.User,
        value1: float,
        member2: discord.User | None,
        value2: float | None,
        member3: discord.User | None,
        value3: float | None,
    ) -> tuple[dict[int, float] | None, str | None]:
        pairs = [(member1, value1)]
        for member, value in ((member2, value2), (member3, value3)):
            if (member is None) != (value is None):
                return None, "Each member must come with a value."
            if member is not None:
                pairs.append((member, value))

        if len({user.id for user, _ in pairs}) != len(pairs):
            return None, "Each member can only appear once."
        if len(pairs) > MAX_MEMBERS:
            return (
                None,
                f"Only up to {MAX_MEMBERS} members are supported in one command. "
                "This is a limitation of Discord slash commands.",
            )

        for user, _ in pairs:
            if interaction.guild.get_member(user.id) is None:
                return None, f"{user.mention} isn't in this server."

        conn = await db.connect()
        share_by_member: dict[int, float] = {}
        for user, value in pairs:
            member_id = await db.ensure_member(
                interaction.guild_id, user.id, user.display_name
            )
            share_by_member[member_id] = value

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
            return None, f"The split must include everyone: {names}."
        return share_by_member, None

    async def _render_split(self, interaction: discord.Interaction, title: str, config: dict):
        shares = await get_shares(config["id"])
        split_type = config["split_type"]
        type_label = "Equal" if split_type == "equal" else "Percentages" if split_type == "percent" else "Weights"
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        embed.add_field(name="Type", value=type_label, inline=False)
        if split_type == "equal":
            embed.add_field(name="Shares", value="Equal split across participants.", inline=False)
        else:
            suffix = "%" if split_type == "percent" else " share(s)"
            for share in shares:
                embed.add_field(
                    name=share["display_name"],
                    value=f"{share['share_percent']:g}{suffix}",
                    inline=True,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @split.command(name="get", description="Show the current expense split.")
    async def split_get(self, interaction: discord.Interaction):
        await self._register(interaction)
        config = await get_active_global_config(interaction.guild_id)
        if config is None:
            await interaction.response.send_message(
                "No custom split set yet — expenses are shared equally by default. "
                "Use `/split set`, `/split set_equal`, or `/split set_weights` to configure one.",
                ephemeral=True,
            )
            return

        await self._render_split(interaction, "Global split", config)

    @split.command(name="clear", description="Clear the global split and fall back to equal split.")
    async def split_clear(self, interaction: discord.Interaction):
        await self._register(interaction)
        await clear_global_config(interaction.guild_id)
        await interaction.response.send_message(
            "Cleared the global split. Expenses now default to equal split unless a category override exists.",
            ephemeral=True,
        )

    @split.command(name="set_equal", description="Set the global split to equal.")
    async def split_set_equal(self, interaction: discord.Interaction):
        changed_by = await self._register(interaction)
        config_id = await create_config(interaction.guild_id, changed_by, "equal", {})
        await set_global_config(interaction.guild_id, config_id)
        await interaction.response.send_message(
            "Global split set to equal.", ephemeral=True
        )

    @split.command(name="set_weights", description="Set global fixed weights (normalized per expense).")
    @app_commands.describe(
        member1="First member",
        percent1="First member weight, e.g. 2",
        member2="Second member",
        percent2="Second member weight, e.g. 1",
        member3="Third member",
        percent3="Third member weight, e.g. 1",
    )
    async def split_set_weights(
        self,
        interaction: discord.Interaction,
        member1: discord.User,
        percent1: float,
        member2: discord.User | None = None,
        percent2: float | None = None,
        member3: discord.User | None = None,
        percent3: float | None = None,
    ):
        changed_by = await self._register(interaction)
        share_by_member, err = await self._member_values(
            interaction, member1, percent1, member2, percent2, member3, percent3
        )
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        assert share_by_member is not None
        err = validate_weights(list(share_by_member.values()))
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        config_id = await create_config(interaction.guild_id, changed_by, "weight", share_by_member)
        await set_global_config(interaction.guild_id, config_id)
        await interaction.response.send_message("Global weighted split set.", ephemeral=True)

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
        share_by_member, err = await self._member_values(
            interaction, member1, percent1, member2, percent2, member3, percent3
        )
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        assert share_by_member is not None
        err = validate_percentages(list(share_by_member.values()))
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        conn = await db.connect()

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
            await set_global_config(interaction.guild_id, config_id)
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

    @split_category.command(name="get", description="Show split override for a category.")
    @app_commands.describe(category="Expense category")
    @app_commands.autocomplete(category=_category_autocomplete)
    async def split_category_get(self, interaction: discord.Interaction, category: str):
        await self._register(interaction)
        category_id = await self._category_id(interaction.guild_id, category)
        if category_id is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return
        config = await get_active_category_config(interaction.guild_id, category_id)
        if config is None:
            await interaction.response.send_message(
                f"No category-specific split for `{category}`. It uses the global split (or equal split if no global split is set).",
                ephemeral=True,
            )
            return
        await self._render_split(interaction, f"Category split — {category}", config)

    @split_category.command(name="clear", description="Clear the split override for a category.")
    @app_commands.describe(category="Expense category")
    @app_commands.autocomplete(category=_category_autocomplete)
    async def split_category_clear(self, interaction: discord.Interaction, category: str):
        await self._register(interaction)
        category_id = await self._category_id(interaction.guild_id, category)
        if category_id is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return
        await clear_category_config(interaction.guild_id, category_id)
        await interaction.response.send_message(
            f"Cleared split override for `{category}`. It now uses the global/equal fallback.",
            ephemeral=True,
        )

    @split_category.command(name="set_equal", description="Set equal split override for a category.")
    @app_commands.describe(category="Expense category")
    @app_commands.autocomplete(category=_category_autocomplete)
    async def split_category_set_equal(self, interaction: discord.Interaction, category: str):
        changed_by = await self._register(interaction)
        category_id = await self._category_id(interaction.guild_id, category)
        if category_id is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return
        config_id = await create_config(interaction.guild_id, changed_by, "equal", {})
        await set_category_config(interaction.guild_id, category_id, config_id)
        await interaction.response.send_message(
            f"Category split for `{category}` set to equal.", ephemeral=True
        )

    @split_category.command(name="set", description="Set percentage split override for a category.")
    @app_commands.describe(
        category="Expense category",
        member1="First member",
        percent1="Their share, e.g. 50",
        member2="Second member",
        percent2="Their share, e.g. 30",
        member3="Third member",
        percent3="Their share, e.g. 20",
    )
    @app_commands.autocomplete(category=_category_autocomplete)
    async def split_category_set(
        self,
        interaction: discord.Interaction,
        category: str,
        member1: discord.User,
        percent1: float,
        member2: discord.User | None = None,
        percent2: float | None = None,
        member3: discord.User | None = None,
        percent3: float | None = None,
    ):
        changed_by = await self._register(interaction)
        category_id = await self._category_id(interaction.guild_id, category)
        if category_id is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return
        share_by_member, err = await self._member_values(
            interaction, member1, percent1, member2, percent2, member3, percent3
        )
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        assert share_by_member is not None
        err = validate_percentages(list(share_by_member.values()))
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        config_id = await create_config(interaction.guild_id, changed_by, "percent", share_by_member)
        await set_category_config(interaction.guild_id, category_id, config_id)
        await interaction.response.send_message(
            f"Category split for `{category}` set.", ephemeral=True
        )

    @split_category.command(name="set_weights", description="Set fixed weights override for a category.")
    @app_commands.describe(
        category="Expense category",
        member1="First member",
        percent1="First member weight, e.g. 2",
        member2="Second member",
        percent2="Second member weight, e.g. 1",
        member3="Third member",
        percent3="Third member weight, e.g. 1",
    )
    @app_commands.autocomplete(category=_category_autocomplete)
    async def split_category_set_weights(
        self,
        interaction: discord.Interaction,
        category: str,
        member1: discord.User,
        percent1: float,
        member2: discord.User | None = None,
        percent2: float | None = None,
        member3: discord.User | None = None,
        percent3: float | None = None,
    ):
        changed_by = await self._register(interaction)
        category_id = await self._category_id(interaction.guild_id, category)
        if category_id is None:
            await interaction.response.send_message(
                f"Category `{category}` doesn't exist. Use `/category add` first.", ephemeral=True
            )
            return
        share_by_member, err = await self._member_values(
            interaction, member1, percent1, member2, percent2, member3, percent3
        )
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        assert share_by_member is not None
        err = validate_weights(list(share_by_member.values()))
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        config_id = await create_config(interaction.guild_id, changed_by, "weight", share_by_member)
        await set_category_config(interaction.guild_id, category_id, config_id)
        await interaction.response.send_message(
            f"Category weighted split for `{category}` set.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SplitCog(bot))
