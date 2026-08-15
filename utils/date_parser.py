import re
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List

ISO_DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"

def parse_date_or_range(raw_input: str) -> Tuple[str, Optional[str]]:
    """
    Parses a string into (start_date, end_date).
    Supports formats:
    - '2026-09-01' -> ('2026-09-01', None)
    - '2026-09-01..2026-09-15' -> ('2026-09-01', '2026-09-15')
    - '2026-09-01:2026-09-15' -> ('2026-09-01', '2026-09-15')
    - '2026-09-01 to 2026-09-15' -> ('2026-09-01', '2026-09-15')
    """
    clean = raw_input.strip()
    separators = ["..", ":", " to ", " - "]
    
    for sep in separators:
        if sep in clean:
            parts = [p.strip() for p in clean.split(sep)]
            if len(parts) == 2:
                start_dt = datetime.strptime(parts[0], "%Y-%m-%d")
                end_dt = datetime.strptime(parts[1], "%Y-%m-%d")
                if end_dt < start_dt:
                    start_dt, end_dt = end_dt, start_dt
                return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")

    # Single date
    dt = datetime.strptime(clean, "%Y-%m-%d")
    return dt.strftime("%Y-%m-%d"), None

def generate_date_sequence(start_date: str, end_date: str, max_days: Optional[int] = 60) -> List[str]:
    """Generates an inclusive sequence of ISO date strings for every consecutive day between start_date and end_date."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    dates = []
    curr = start_dt
    while curr <= end_dt:
        dates.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=1)
        if max_days and len(dates) >= max_days:
            break
    return dates

def get_preset_range(preset_key: str) -> Tuple[str, str]:
    """Calculates ISO start and end dates for preset options."""
    today = datetime.now(timezone.utc).date()
    if preset_key == "this_weekend":
        # Find next Saturday (5)
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        sat = today + timedelta(days=days_until_sat)
        sun = sat + timedelta(days=1)
        return sat.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d")
    elif preset_key == "next_7_days":
        start = today + timedelta(days=1)
        end = today + timedelta(days=7)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    elif preset_key == "next_14_days":
        start = today + timedelta(days=1)
        end = today + timedelta(days=14)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    else:
        raise ValueError(f"Unknown preset_key: {preset_key}")
