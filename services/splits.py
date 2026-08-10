import aiosqlite

import db.database as db


async def get_active_config(guild_id: int) -> aiosqlite.Row | None:
    """Return the most recently created split config for the guild, if any."""
    conn = await db.connect()
    cursor = await conn.execute(
        "SELECT * FROM split_configs WHERE guild_id = ? ORDER BY id DESC LIMIT 1",
        (guild_id,),
    )
    return await cursor.fetchone()


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
