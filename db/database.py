import aiosqlite

import config

_conn: aiosqlite.Connection | None = None


async def connect() -> aiosqlite.Connection:
    """Return the shared connection, creating it on first use."""
    global _conn
    if _conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(config.DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def init_schema() -> None:
    """Create all tables if they don't exist yet."""
    conn = await connect()
    schema = (config.BASE_DIR / "db" / "schema.sql").read_text()
    await conn.executescript(schema)
    await conn.commit()


async def get_guild_config(guild_id: int) -> aiosqlite.Row:
    conn = await connect()
    await ensure_guild(guild_id)
    cursor = await conn.execute("SELECT * FROM guilds WHERE guild_id = ?", (guild_id,))
    row = await cursor.fetchone()
    assert row is not None
    return row


async def ensure_guild(guild_id: int, *, timezone: str | None = None) -> None:
    conn = await connect()
    await conn.execute(
        "INSERT OR IGNORE INTO guilds (guild_id, timezone) VALUES (?, ?)",
        (guild_id, timezone or config.DEFAULT_TZ),
    )
    await conn.commit()


async def ensure_member(guild_id: int, user_id: int, display_name: str) -> int:
    """Register a Discord user as a member of this guild; return the row id."""
    conn = await connect()
    await ensure_guild(guild_id)
    cursor = await conn.execute(
        "SELECT id FROM members WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    row = await cursor.fetchone()
    if row is not None:
        if display_name:
            await conn.execute(
                "UPDATE members SET display_name = ? WHERE id = ?",
                (display_name, row["id"]),
            )
            await conn.commit()
        return row["id"]
    cursor = await conn.execute(
        "INSERT INTO members (guild_id, user_id, display_name) VALUES (?, ?, ?)",
        (guild_id, user_id, display_name),
    )
    await conn.commit()
    return cursor.lastrowid
