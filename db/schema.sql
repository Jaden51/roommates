CREATE TABLE IF NOT EXISTS guilds (
    guild_id   INTEGER PRIMARY KEY,
    channel_id INTEGER,
    timezone   TEXT NOT NULL DEFAULT 'UTC'
);

-- Members are cached on first interaction so "everyone must approve"
-- has a well-defined set.
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    UNIQUE (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES members(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (guild_id, name)
);

-- Versioned global split. Only one row per guild is "active" (see below).
CREATE TABLE IF NOT EXISTS split_configs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    changed_by INTEGER REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS split_shares (
    config_id     INTEGER NOT NULL REFERENCES split_configs(id) ON DELETE CASCADE,
    member_id     INTEGER NOT NULL REFERENCES members(id),
    share_percent INTEGER NOT NULL CHECK (share_percent > 0),
    PRIMARY KEY (config_id, member_id)
);

-- Pending split-change proposals, approved via the same all-members flow.
CREATE TABLE IF NOT EXISTS split_proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    proposed_by INTEGER NOT NULL REFERENCES members(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
    config_id   INTEGER REFERENCES split_configs(id)
);

CREATE TABLE IF NOT EXISTS split_proposal_shares (
    proposal_id   INTEGER NOT NULL REFERENCES split_proposals(id) ON DELETE CASCADE,
    member_id     INTEGER NOT NULL REFERENCES members(id),
    share_percent INTEGER NOT NULL CHECK (share_percent > 0),
    PRIMARY KEY (proposal_id, member_id)
);

CREATE TABLE IF NOT EXISTS split_proposal_votes (
    proposal_id INTEGER NOT NULL REFERENCES split_proposals(id) ON DELETE CASCADE,
    voter_id    INTEGER NOT NULL REFERENCES members(id),
    decision    TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    voted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (proposal_id, voter_id)
);

-- Amounts stored as integer cents to avoid float rounding issues.
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    payer_id     INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    note         TEXT NOT NULL DEFAULT '',
    month_key    TEXT NOT NULL,  -- 'YYYY-MM'
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    message_id   INTEGER,  -- Discord message holding the approval buttons
    required_voters TEXT NOT NULL DEFAULT '[]'  -- JSON array of member ids who must approve
);

CREATE TABLE IF NOT EXISTS expense_approvals (
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    decision   TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    voted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (expense_id, member_id)
);

CREATE TABLE IF NOT EXISTS chores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    created_by   INTEGER NOT NULL REFERENCES members(id),
    freq         TEXT NOT NULL CHECK (freq IN ('weekly', 'monthly_nth', 'monthly_day')),
    day_of_week  INTEGER,  -- 0=Mon..6=Sun; used by 'weekly' and 'monthly_nth'
    nth          INTEGER,  -- 1..4, or -1 for last; used by 'monthly_nth'
    day_of_month INTEGER,  -- 1..31; used by 'monthly_day'
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (guild_id, name)
);

-- Recorded reminders, so a restart never double-posts the same chore.
CREATE TABLE IF NOT EXISTS chore_occurrences (
    chore_id INTEGER NOT NULL REFERENCES chores(id) ON DELETE CASCADE,
    due_date TEXT NOT NULL,  -- 'YYYY-MM-DD'
    PRIMARY KEY (chore_id, due_date)
);
