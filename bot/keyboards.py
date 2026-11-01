"""Inline keyboards. Callback data is '<prefix>:<value>' so each wizard only sees its own buttons."""
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.airports_data import REGION_LABELS, airport_name

CANCEL = "cancel"
BACK = "back"
NOOP = "noop"
STOP_TASK = "task:stop"
TRACK_ADD = "trk:add"
# '/search' hands a region destination to '/explore' with 'exp:from:<ORIGIN>:<region>'.
EXPLORE_FROM_SEARCH = rf"^exp:from:[A-Z]{{3}}:({'|'.join(REGION_LABELS)})$"

RESULT_LIMITS = [5, 10, 15, 20]
DEFAULT_RESULT_LIMIT = 10


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def cancel_button() -> InlineKeyboardButton:
    return button("❌ Cancel", CANCEL)


def back_button(data: str = BACK) -> InlineKeyboardButton:
    return button("⬅️ Back", data)


def markup(*rows: list[InlineKeyboardButton], cancel: bool = True, back: bool = False,
           back_data: str = BACK) -> InlineKeyboardMarkup:
    """Rows of buttons, ending with [⬅️ Back] [❌ Cancel] when asked for."""
    keyboard = [row for row in rows if row]
    last_row = ([back_button(back_data)] if back else []) + ([cancel_button()] if cancel else [])
    if last_row:
        keyboard.append(last_row)
    return InlineKeyboardMarkup(keyboard)


def pairs(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def airport_choices(prefix: str, matches: list[tuple[str, str, str, float]], back: bool = False) -> InlineKeyboardMarkup:
    return markup(*[[button(f"{code} - {name} ({country})", f"{prefix}:{code}")] for code, name, country, _ in matches],
                  back=back)


def recent_airports(prefix: str, codes: list[str]) -> InlineKeyboardMarkup:
    return markup(*[[button(f"{code} - {airport_name(code) or code}", f"{prefix}:{code}")] for code in codes])


def regions(prefix: str, back_data: str = BACK) -> InlineKeyboardMarkup:
    return markup(*pairs([button(label, f"{prefix}:{key}") for key, label in REGION_LABELS.items()]),
                  back=True, back_data=back_data)


def sort_modes(prefix: str, default: Optional[str] = None) -> InlineKeyboardMarkup:
    def label(text: str, mode: str) -> str:
        return f"{text} (Default)" if mode == default else text
    return markup(
        [button(label("💥 Biggest Discount %", "discount"), f"{prefix}:discount"),
         button(label("💶 Cheapest Price", "price"), f"{prefix}:price")],
        [button(label("🔀 Both Lists", "both"), f"{prefix}:both")],
        back=True,
    )


def flight_types(prefix: str) -> InlineKeyboardMarkup:
    return markup(
        [button("✈️ Direct Flights Only", f"{prefix}:1")],
        [button("🔄 Any (Direct & With Stops)", f"{prefix}:0")],
        back=True,
    )


def result_limits(prefix: str) -> InlineKeyboardMarkup:
    labels = [f"{n} (Default)" if n == DEFAULT_RESULT_LIMIT else str(n) for n in RESULT_LIMITS]
    return markup(*pairs([button(text, f"{prefix}:{n}") for text, n in zip(labels, RESULT_LIMITS, strict=True)]), back=True)


def stop_markup() -> InlineKeyboardMarkup:
    return markup([button("⏹ Stop", STOP_TASK)], cancel=False)


def track_button_data(origin: str, destination: str, start: str, end: Optional[str],
                      budget: float, direct_only: bool = False) -> str:
    """Callback data for a button that starts tracking a route at a given budget."""
    return f"{TRACK_ADD}:{origin}:{destination}:{start}:{end or ''}:{budget:.2f}:{int(direct_only)}"


def explore_from_search_prefix(origin: str) -> str:
    return f"exp:from:{origin}"

