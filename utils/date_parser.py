from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

MAX_RANGE_DAYS = 330
RANGE_SEPARATORS = ["..", ":", " to ", " - "]
PRESETS = {
    "next_7_days": "🗓️ Next 7 Days",
    "next_14_days": "✈️ Next 14 Days",
    "this_weekend": "📅 This Weekend",
}


@lru_cache(maxsize=1)
def _bot_timezone():
    from config import get_timezone
    return get_timezone()


def today_local() -> date:
    """Today in the bot's timezone (TIMEZONE, else the server's), the same one digest times use."""
    return datetime.now(_bot_timezone()).date()


def parse_date_or_range(raw_input: str) -> tuple[str, Optional[str]]:
    """Parse 'YYYY-MM-DD' or a range like 'YYYY-MM-DD..YYYY-MM-DD' into (start, end).

    Ranges also accept ':', ' to ' and ' - ' as separators. Reversed ranges
    are swapped. Raises ValueError on anything else.
    """
    clean = raw_input.strip()
    for sep in RANGE_SEPARATORS:
        parts = [p.strip() for p in clean.split(sep)]
        if len(parts) == 2:
            start, end = sorted(date.fromisoformat(p) for p in parts)
            if start == end:
                return start.isoformat(), None
            return start.isoformat(), end.isoformat()
    return date.fromisoformat(clean).isoformat(), None


def generate_date_sequence(start_date: str, end_date: str, max_days: Optional[int] = MAX_RANGE_DAYS) -> list[str]:
    """Every day from start_date to end_date inclusive, capped at max_days."""
    current = date.fromisoformat(start_date)
    last = date.fromisoformat(end_date)
    dates = []
    while current <= last and (not max_days or len(dates) < max_days):
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def days_ahead_window(days: int, today: Optional[date] = None) -> tuple[str, str]:
    """Tomorrow through `days` days from today."""
    today = today or today_local()
    return (today + timedelta(days=1)).isoformat(), (today + timedelta(days=days)).isoformat()


def get_preset_range(preset_key: str, today: Optional[date] = None) -> tuple[str, str]:
    today = today or today_local()
    if preset_key == "this_weekend":
        days_until_saturday = (5 - today.weekday()) % 7 or 7
        saturday = today + timedelta(days=days_until_saturday)
        return saturday.isoformat(), (saturday + timedelta(days=1)).isoformat()
    if preset_key == "next_7_days":
        return days_ahead_window(7, today)
    if preset_key == "next_14_days":
        return days_ahead_window(14, today)
    raise ValueError(f"Unknown preset_key: {preset_key}")


def is_past(iso_date: str, today: Optional[date] = None) -> bool:
    return iso_date < (today or today_local()).isoformat()


def window_problem(start: str, end: Optional[str], today: Optional[date] = None,
                   max_days: int = MAX_RANGE_DAYS) -> Optional[str]:
    """Why a departure date or range can't be used, or None if it's fine."""
    if is_past(start, today):
        return "That date is in the past. Pick a future date."
    if end and (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 > max_days:
        return f"That range is too long: the most you can search is {max_days} days."
    return None


def describe_window(start: str, end: Optional[str]) -> str:
    return f"{start} ➔ {end}" if end else start
