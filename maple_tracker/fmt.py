"""Number and time formatting for the overlay and summary."""
from datetime import datetime


def commas(n):
    return "—" if n is None else f"{round(n):,}"


def short(n, sign=False):
    """182,340 -> '182.3k', 1,250,000 -> '1.25M'."""
    if n is None:
        return "—"
    s = "+" if sign and n > 0 else "-" if n < 0 else ""
    a = abs(n)
    if a >= 1_000_000:
        body = f"{a / 1_000_000:.2f}M"
    elif a >= 1_000:
        body = f"{a / 1_000:.1f}k"
    else:
        body = f"{a:.0f}"
    return s + body


def clock(seconds):
    s = int(seconds or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def eta(seconds):
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    if m >= 60 * 48:
        return "> 2 days"
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def at(seconds, now):
    """When something `seconds` from `now` happens, as a clock time: '21:45', 'Thu 09:10'
    when it's not today, or '' when it's more than 2 days off (or not known)."""
    if seconds is None or seconds > 48 * 3600:
        return ""
    when = datetime.fromtimestamp(now + seconds)
    return when.strftime("%H:%M") if when.date() == datetime.fromtimestamp(now).date() \
        else when.strftime("%a %H:%M")
