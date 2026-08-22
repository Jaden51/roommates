import aiosqlite

import db.database as db

PERCENT_TOLERANCE = 0.005


async def get_active_global_config(guild_id: int) -> aiosqlite.Row | None:
    """Return the active global split config for the guild, if any."""
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT c.*
        FROM global_split_configs g
        JOIN split_configs c ON c.id = g.config_id
        WHERE g.guild_id = ?
        """,
        (guild_id,),
    )
    return await cursor.fetchone()


async def get_active_category_config(guild_id: int, category_id: int) -> aiosqlite.Row | None:
    """Return the active category override split config, if any."""
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT c.*
        FROM category_split_configs cs
        JOIN split_configs c ON c.id = cs.config_id
        WHERE cs.guild_id = ? AND cs.category_id = ?
        """,
        (guild_id, category_id),
    )
    return await cursor.fetchone()


async def resolve_config(guild_id: int, category_id: int | None) -> aiosqlite.Row | None:
    """Resolve split config by priority: category override, then global default."""
    if category_id is not None:
        category_config = await get_active_category_config(guild_id, category_id)
        if category_config is not None:
            return category_config
    return await get_active_global_config(guild_id)


async def get_active_config(guild_id: int) -> aiosqlite.Row | None:
    """Backward-compatible alias for the active global split config."""
    return await get_active_global_config(guild_id)


async def create_config(
    guild_id: int,
    changed_by: int | None,
    split_type: str,
    shares_by_member: dict[int, float],
) -> int:
    """Create a split config and return its id."""
    conn = await db.connect()
    cursor = await conn.execute(
        "INSERT INTO split_configs (guild_id, changed_by, split_type) VALUES (?, ?, ?)",
        (guild_id, changed_by, split_type),
    )
    config_id = cursor.lastrowid
    for member_id, share_value in shares_by_member.items():
        await conn.execute(
            "INSERT INTO split_shares (config_id, member_id, share_percent) VALUES (?, ?, ?)",
            (config_id, member_id, share_value),
        )
    await conn.commit()
    return config_id


async def set_global_config(guild_id: int, config_id: int) -> None:
    conn = await db.connect()
    await conn.execute(
        """
        INSERT INTO global_split_configs (guild_id, config_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET config_id = excluded.config_id
        """,
        (guild_id, config_id),
    )
    await conn.commit()


async def clear_global_config(guild_id: int) -> None:
    conn = await db.connect()
    await conn.execute("DELETE FROM global_split_configs WHERE guild_id = ?", (guild_id,))
    await conn.commit()


async def set_category_config(guild_id: int, category_id: int, config_id: int) -> None:
    conn = await db.connect()
    await conn.execute(
        """
        INSERT INTO category_split_configs (guild_id, category_id, config_id)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, category_id) DO UPDATE SET config_id = excluded.config_id
        """,
        (guild_id, category_id, config_id),
    )
    await conn.commit()


async def clear_category_config(guild_id: int, category_id: int) -> None:
    conn = await db.connect()
    await conn.execute(
        "DELETE FROM category_split_configs WHERE guild_id = ? AND category_id = ?",
        (guild_id, category_id),
    )
    await conn.commit()


def validate_percentages(values: list[float]) -> str | None:
    if any(value <= 0 for value in values):
        return "Percentages must be positive."
    if abs(sum(values) - 100) > PERCENT_TOLERANCE:
        return "Percentages must add up to 100."
    return None


def validate_weights(values: list[float]) -> str | None:
    if any(value <= 0 for value in values):
        return "Weights must be positive."
    return None


async def get_shares(config_id: int) -> list[aiosqlite.Row]:
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT s.share_percent, m.id AS member_id, m.display_name
        FROM split_shares s
        JOIN members m ON m.id = s.member_id
        WHERE s.config_id = ?
        ORDER BY m.display_name
        """,
        (config_id,),
    )
    return await cursor.fetchall()
