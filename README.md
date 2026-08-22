# Roommates

A Discord bot that helps roommates, couples, or anyone living together stay organized. Track shared expenses with an approval flow, get a monthly "who owes whom" statement, and never forget a chore again.

Built with Python, discord.py, and SQLite. Self-hosted on your own machine.

---

## Features

### Shared expenses

- Create your own expense categories (Groceries, Rent, Utilities, ...) with `/category add`.
- Anyone records what they paid with `/expense add` — category + amount + optional note.
- The expense is posted with **Approve** / **Reject** buttons; it only counts once **every** other member has approved. Any rejection throws it out.
- All money is handled in integer cents, so there are no floating-point surprises.

### Customizable split

- Set a **global default split** for all expenses:
  - percentages with `/split set` (approval flow),
  - equal split with `/split set_equal`,
  - fixed weights/shares with `/split set_weights`.
- Set **category-specific overrides** with `/split category set`, `/split category set_equal`, or `/split category set_weights`.
- Split resolution is: category override → global default → equal fallback.
- Each expense is settled under the split that was in effect when it was approved, so mid-month changes don't rewrite history.

### Monthly statement

- On the last day of every month the bot posts a statement: the month's expenses and exactly **who owes whom** — using a minimal-transaction settlement so nobody makes a dozen tiny transfers.
- Pull it any time with `/statement show`.

### Chore reminders

- Create recurring chores with flexible schedules:
  - `Weekly` — every Sunday
  - `Biweekly` — every 14 days from a start date, or every other selected weekday
  - `Monthly weekday` — first / second / ... / last Sunday of the month
  - `Monthly day` — on the 15th of every month
- The bot posts a reminder on each due day in your chosen channel. Restart-safe, so no double reminders.

---

## Commands

| Command | Description |
| --- | --- |
| `/setup channel #channel` | Choose where reminders and statements are posted |
| `/setup timezone <IANA>` | Set this server's timezone |
| `/setup show` | Show current server config |
| `/category add <name>` | Create an expense category |
| `/category list` | List categories |
| `/expense add <category> <amount> [note]` | Record an expense you paid (others approve it) |
| `/expense list [YYYY-MM]` | List a month's expenses |
| `/split get` | Show the current split |
| `/split set <member> <pct> [...]` | Propose a new split (requires approval) |
| `/split set_equal` | Set global default to equal split |
| `/split set_weights <member> <weight> [...]` | Set global fixed-weight split |
| `/split clear` | Clear global split (falls back to equal) |
| `/split category get <category>` | Show category split override |
| `/split category set <category> <member> <pct> [...]` | Set category percentage override |
| `/split category set_equal <category>` | Set category override to equal split |
| `/split category set_weights <category> <member> <weight> [...]` | Set category fixed-weight override |
| `/split category clear <category>` | Clear category split override |
| `/chore create <name> <freq> [...]` | Create a recurring chore reminder |
| `/chore list` | List chores |
| `/chore delete <name>` | Delete a chore |
| `/chore next <name>` | Preview upcoming occurrences of a chore |
| `/statement show [YYYY-MM]` | Post the monthly "who owes whom" statement |

`/setup` requires the **Manage Server** permission; everything else is available to any member.

---

## How it works

1. **Onboarding** — everyone who uses the bot is registered as a member of the server. The "everyone must approve" rule applies to this set, so a new member can't accidentally block an old expense.
2. **Expenses** — `/expense add` posts an approval card to your configured channel. Votes update it live; the expense is locked in only when everyone has approved.
3. **Settlement** — at month's end (or via `/statement show`) each approved expense is split per its snapshot, balances are netted out, and a minimal set of transfers is computed: *"Sam owes Alex $30.00"*.
4. **Chores** — a background loop checks every guild's schedule each hour and posts reminders for anything due today, once per day.

---

## Setup

See [SETUP.md](SETUP.md) for full instructions. In short:

```bash
cp .env.example .env   # add your BOT_TOKEN
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bot.py
```

Then invite the bot with the `bot` and `applications.commands` scopes and run `/setup channel` to pick where it posts.

---

## Data storage

Everything lives in a single SQLite file at `data/roommates.db` — no database server required. Back it up by copying that file (while the bot is stopped) or inspect it with `sqlite3 data/roommates.db`.

---

## Tech stack

- **Python 3.11+** with **discord.py 2.4** (slash commands, buttons, background tasks)
- **SQLite** via **aiosqlite**
- Self-hosted; the bot runs while the script is running on your machine
