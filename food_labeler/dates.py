"""Date helpers: quick "use by" offsets and friendly formats.

Dates are stored in label documents as ISO strings (YYYY-MM-DD) and only
formatted for display/printing here, so the date style setting can change
without touching saved files.
"""
from __future__ import annotations

import calendar
import datetime as dt

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# (button text, kind, amount)
QUICK = [
    ("+3 days", "days", 3),
    ("+5 days", "days", 5),
    ("+1 week", "days", 7),
    ("+2 weeks", "days", 14),
    ("+1 month", "months", 1),
]

STYLES = {
    "us": "Nov 20, 2026",
    "dmy": "20 Nov 2026",
    "numeric": "11/20/2026",
}


def today() -> dt.date:
    """Today's local date (one place to patch in tests)."""
    return dt.date.today()


def parse(value, default: dt.date | None = None) -> dt.date | None:
    """A date, or an ISO string, to a date; anything else gives ``default``."""
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def add_months(d: dt.date, n: int) -> dt.date:
    """Add n calendar months, clamping the day (Jan 31 + 1 month = Feb 28/29)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, day)


def quick(base: dt.date, kind: str, amount: int) -> dt.date:
    """Apply one of the QUICK offsets ("days" or "months") to base."""
    if kind == "months":
        return add_months(base, amount)
    return base + dt.timedelta(days=amount)


def fmt(d: dt.date | None, style: str = "us") -> str:
    """Format for the label. style: us | dmy | numeric | mdy_short (date sticker)."""
    if d is None:
        return ""
    if style == "dmy":
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    if style == "numeric":
        return f"{d.month}/{d.day}/{d.year}"
    if style == "mdy_short":
        return f"{d.month}/{d.day}/{d.year % 100:02d}"
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def fmt_long(d: dt.date | None) -> str:
    """For on-screen buttons: 'Friday, Nov 20, 2026'."""
    if d is None:
        return "No date"
    return f"{calendar.day_name[d.weekday()]}, {fmt(d, 'us')}"
