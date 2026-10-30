"""Month-grid date picker rendered as an inline keyboard."""
import calendar
from datetime import date
from typing import Optional

from telegram import InlineKeyboardMarkup

from bot.keyboards import NOOP, button, cancel_button

WEEKDAY_HEADER = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
SINGLE = "single"
RANGE = "range"


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def calendar_markup(
    prefix: str,
    year: int,
    month: int,
    today: date,
    mode: str = RANGE,
    range_start: Optional[date] = None,
    back_data: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Days before today (or before the chosen range start) are shown as '·' and can't be picked.

    Callback data: '<prefix>:nav:YYYY-MM', '<prefix>:mode:<single|range>', '<prefix>:day:YYYY-MM-DD'.
    """
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    first_allowed = max(today, range_start) if range_start else today

    keyboard = [
        [
            button("«", f"{prefix}:nav:{prev_year:04d}-{prev_month:02d}"),
            button(f"{calendar.month_abbr[month]} {year}", NOOP),
            button("»", f"{prefix}:nav:{next_year:04d}-{next_month:02d}"),
        ],
        [button(day, NOOP) for day in WEEKDAY_HEADER],
    ]
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(button(" ", NOOP))
                continue
            current = date(year, month, day)
            if current < first_allowed:
                row.append(button("·", NOOP))
            elif current == range_start:
                row.append(button(f"🚩{day}", f"{prefix}:day:{current.isoformat()}"))
            else:
                row.append(button(str(day), f"{prefix}:day:{current.isoformat()}"))
        keyboard.append(row)

    toggle = (button("📅 Pick a range", f"{prefix}:mode:{RANGE}") if mode == SINGLE
              else button("📅 Pick one day", f"{prefix}:mode:{SINGLE}"))
    keyboard.append([toggle])
    keyboard.append(([button("⬅️ Back", back_data)] if back_data else []) + [cancel_button()])
    return InlineKeyboardMarkup(keyboard)

