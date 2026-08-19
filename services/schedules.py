import datetime

import aiosqlite

import db.database as db

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NTH_WORDS = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}


def describe_schedule(chore: aiosqlite.Row) -> str:
    freq = chore["freq"]
    if freq == "weekly":
        return f"Every {WEEKDAYS[chore['day_of_week']]}"
    if freq == "biweekly":
        mode = chore["biweekly_mode"]
        start = chore["start_date"]
        if mode == "every_14_days":
            return f"Every 14 days from {start}"
        if mode == "every_other_weekday":
            return f"Every other {WEEKDAYS[chore['day_of_week']]} starting {start}"
        return "Biweekly"
    if freq == "monthly_nth":
        nth = chore["nth"]
        word = "Last" if nth == -1 else NTH_WORDS[nth]
        return f"{word} {WEEKDAYS[chore['day_of_week']]} of every month"
    if freq == "monthly_day":
        day = chore["day_of_month"]
        suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"On the {day}{suffix} of every month"
    return "Unknown schedule"


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> datetime.date:
    """Return the date of the nth (or last, if nth == -1) weekday of the month."""
    first = datetime.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    first_occurrence = first + datetime.timedelta(days=offset)
    if nth == -1:
        day = first_occurrence + datetime.timedelta(weeks=4)
        if day.month != month:
            day -= datetime.timedelta(weeks=1)
        return day
    return first_occurrence + datetime.timedelta(weeks=nth - 1)


def matches(chore: aiosqlite.Row, date: datetime.date) -> bool:
    if chore["freq"] == "weekly":
        return date.weekday() == chore["day_of_week"]
    if chore["freq"] == "biweekly":
        start = chore["start_date"]
        if not start:
            return False
        try:
            start_date = datetime.datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            return False
        mode = chore["biweekly_mode"]
        if mode == "every_14_days":
            delta = (date - start_date).days
            return delta >= 0 and delta % 14 == 0
        if mode == "every_other_weekday":
            if chore["day_of_week"] is None:
                return False
            first = start_date + datetime.timedelta(
                days=(chore["day_of_week"] - start_date.weekday()) % 7
            )
            delta = (date - first).days
            return date.weekday() == chore["day_of_week"] and delta >= 0 and delta % 14 == 0
        return False
    if chore["freq"] == "monthly_nth":
        target = nth_weekday(date.year, date.month, chore["day_of_week"], chore["nth"])
        return date == target
    if chore["freq"] == "monthly_day":
        return date.day == chore["day_of_month"]
    return False


def next_occurrences(
    chore: aiosqlite.Row, start: datetime.date, count: int = 5
) -> list[datetime.date]:
    out: list[datetime.date] = []
    current = start
    max_scan = count * 62 + 10
    for _ in range(max_scan):
        if matches(chore, current):
            out.append(current)
            if len(out) == count:
                break
        current += datetime.timedelta(days=1)
    return out


async def due_chores(guild_id: int, date: datetime.date) -> list[aiosqlite.Row]:
    """Return chores in the guild whose schedule matches the given date."""
    conn = await db.connect()
    cursor = await conn.execute(
        "SELECT * FROM chores WHERE guild_id = ? ORDER BY name", (guild_id,)
    )
    return [chore for chore in await cursor.fetchall() if matches(chore, date)]
