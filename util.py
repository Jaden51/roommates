from decimal import Decimal, InvalidOperation


def to_cents(amount: float) -> int:
    """Convert a dollar amount to integer cents. Raises ValueError if invalid."""
    try:
        cents = int(Decimal(str(amount)).quantize(Decimal("0.01")) * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("That doesn't look like a valid amount.")
    if cents <= 0:
        raise ValueError("Amount must be greater than 0.")
    return cents


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"
