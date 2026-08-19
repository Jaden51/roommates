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
    await _migrate_chores_schema(conn)
    await conn.commit()


async def _migrate_chores_schema(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'chores'"
    )
    row = await cursor.fetchone()
    if row is None:
        return

    sql = row["sql"] or ""
    cursor = await conn.execute("PRAGMA table_info(chores)")
    columns = {column["name"] for column in await cursor.fetchall()}
    needs_migration = (
        "biweekly_mode" not in columns
        or "start_date" not in columns
        or "'biweekly'" not in sql
    )
    if not needs_migration:
        return

    await conn.execute("PRAGMA foreign_keys = OFF")
    try:
        try:
            await conn.execute("BEGIN")
            await conn.execute(
                """
                CREATE TABLE chores_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
                    name          TEXT NOT NULL,
                    created_by    INTEGER NOT NULL REFERENCES members(id),
                    freq          TEXT NOT NULL CHECK (freq IN ('weekly', 'biweekly', 'monthly_nth', 'monthly_day')),
                    day_of_week   INTEGER,
                    nth           INTEGER,
                    day_of_month  INTEGER,
                    biweekly_mode TEXT CHECK (biweekly_mode IN ('every_14_days', 'every_other_weekday')),
                    start_date    TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE (guild_id, name)
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO chores_new (id, guild_id, name, created_by, freq, day_of_week, nth, day_of_month, created_at)
                SELECT id, guild_id, name, created_by, freq, day_of_week, nth, day_of_month, created_at
                FROM chores
                """
            )
            await conn.execute("DROP TABLE chores")
            await conn.execute("ALTER TABLE chores_new RENAME TO chores")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
    finally:
        await conn.execute("PRAGMA foreign_keys = ON")


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
