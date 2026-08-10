import datetime
import json

import aiosqlite
import discord

import db.database as db
from util import format_money


def _equal_shares(amount_cents: int, member_ids: list[int]) -> dict[int, int]:
    n = len(member_ids)
    base, remainder = divmod(amount_cents, n)
    return {mid: base + (1 if i < remainder else 0) for i, mid in enumerate(member_ids)}


async def _config_shares(
    split_config_id: int, amount_cents: int, member_ids: list[int]
) -> dict[int, int]:
    """Allocate the amount using a split config, renormalized over the expense's
    members (largest-remainder rounding so shares always sum exactly)."""
    conn = await db.connect()
    cursor = await conn.execute(
        "SELECT member_id, share_percent FROM split_shares WHERE config_id = ?",
        (split_config_id,),
    )
    rows = await cursor.fetchall()
    weights = {row["member_id"]: row["share_percent"] for row in rows}
    total = sum(weights.get(mid, 0) for mid in member_ids)
    if total <= 0:
        return _equal_shares(amount_cents, member_ids)

    raw = {mid: amount_cents * weights.get(mid, 0) / total for mid in member_ids}
    floored = {mid: int(raw[mid]) for mid in member_ids}
    remainder = amount_cents - sum(floored.values())
    order = sorted(member_ids, key=lambda mid: raw[mid] - floored[mid], reverse=True)
    for mid in order[:remainder]:
        floored[mid] += 1
    return floored


async def compute_settlement(guild_id: int, month_key: str) -> dict | None:
    """Compute the monthly settlement for a guild. Returns None if no approved
    expenses exist for that month."""
    conn = await db.connect()
    cursor = await conn.execute(
        """
        SELECT e.*, c.name AS category_name
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        WHERE e.guild_id = ? AND e.month_key = ? AND e.status = 'approved'
        ORDER BY e.created_at
        """,
        (guild_id, month_key),
    )
    expenses = await cursor.fetchall()
    if not expenses:
        return None

    cursor = await conn.execute(
        "SELECT id, display_name FROM members WHERE guild_id = ?", (guild_id,)
    )
    member_names = {row["id"]: row["display_name"] for row in await cursor.fetchall()}

    detail: list[dict] = []
    net: dict[int, int] = {}
    for exp in expenses:
        member_ids = json.loads(exp["required_voters"]) + [exp["payer_id"]]
        member_ids = list(dict.fromkeys(member_ids))
        if exp["split_config_id"]:
            shares = await _config_shares(exp["split_config_id"], exp["amount_cents"], member_ids)
        else:
            shares = _equal_shares(exp["amount_cents"], member_ids)

        payer = exp["payer_id"]
        detail.append({"expense": exp, "shares": shares})
        # Others owe the payer everything except the payer's own share.
        net[payer] = net.get(payer, 0) + (exp["amount_cents"] - shares.get(payer, 0))
        for mid, share_cents in shares.items():
            if mid != payer:
                net[mid] = net.get(mid, 0) - share_cents

    creditors = sorted(((m, v) for m, v in net.items() if v > 0), key=lambda x: -x[1])
    debtors = sorted(((m, -v) for m, v in net.items() if v < 0), key=lambda x: -x[1])

    payments: list[tuple[int, int, int]] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, d = debtors[i]
        creditor, c = creditors[j]
        pay = min(d, c)
        payments.append((debtor, creditor, pay))
        debtors[i] = (debtor, d - pay)
        creditors[j] = (creditor, c - pay)
        if d - pay == 0:
            i += 1
        if c - pay == 0:
            j += 1

    return {
        "month_key": month_key,
        "expenses": detail,
        "net": net,
        "payments": payments,
        "member_names": member_names,
    }


def build_statement_embed(data: dict) -> discord.Embed:
    month_label = datetime.datetime.strptime(data["month_key"], "%Y-%m").strftime("%B %Y")
    embed = discord.Embed(title=f"Monthly statement — {month_label}", color=discord.Color.green())

    names = data["member_names"]
    expense_lines = [
        f"{item['expense']['category_name']} — {format_money(item['expense']['amount_cents'])} "
        f"(paid by {names.get(item['expense']['payer_id'], 'Unknown')})"
        for item in data["expenses"]
    ]
    embed.add_field(name="Expenses", value="\n".join(expense_lines), inline=False)

    payments = data["payments"]
    if payments:
        lines = [
            f"{names.get(debtor, 'Unknown')} owes {names.get(creditor, 'Unknown')} {format_money(amount)}"
            for debtor, creditor, amount in payments
        ]
        embed.add_field(name="Who owes whom", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Who owes whom", value="Everyone is settled up.", inline=False)

    total = sum(item["expense"]["amount_cents"] for item in data["expenses"])
    embed.set_footer(text=f"{len(data['expenses'])} expense(s) · {format_money(total)} total")
    return embed
