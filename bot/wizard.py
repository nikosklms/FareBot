"""Building blocks shared by the /search, /track, /explore and /digest wizards."""
import asyncio
import logging
import math
import warnings
from datetime import date
from functools import wraps
from typing import Any, Awaitable, Callable, Coroutine, Optional

from telegram import InlineKeyboardMarkup, Message, Update
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import keyboards
from bot.date_picker import RANGE, SINGLE, calendar_markup
from bot.keyboards import BACK, CANCEL, button, markup, pairs
from bot.lifecycle import track_task
from bot.services import get_services
from services.airports_data import find_region
from utils.date_parser import MAX_RANGE_DAYS, PRESETS, get_preset_range, parse_date_or_range, today_local, window_problem

logger = logging.getLogger(__name__)

# Wizards track state per user and chat, not per message; button presses on old messages are fine.
warnings.filterwarnings("ignore", message="If 'per_message=False'", category=PTBUserWarning)

Context = ContextTypes.DEFAULT_TYPE
OnAirport = Callable[[Update, Context, str], Awaitable[int]]
OnDates = Callable[[Update, Context, str, Optional[str]], Awaitable[int]]
OnDays = Callable[[Update, Context, int], Awaitable[int]]
Ask = Callable[[Update, Context], Awaitable[int]]

TEXT = filters.TEXT & ~filters.COMMAND
TASK_KEY = "running_task"
ACTIVE_WIZARD_KEY = "active_wizard"
CALENDAR_KEY = "calendar"


# ----------------------------------------------------------------------
# Conversation plumbing
# ----------------------------------------------------------------------

def start_draft(context: Context, name: str) -> dict[str, Any]:
    """Fresh state for a wizard, which also becomes the one that answers typed input."""
    context.user_data.pop(CALENDAR_KEY, None)
    context.user_data[ACTIVE_WIZARD_KEY] = name
    context.user_data[name] = {}
    return context.user_data[name]


def draft(context: Context, name: str) -> dict[str, Any]:
    return context.user_data.setdefault(name, {})


async def respond(update: Update, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> Message:
    """Edit the message whose button was pressed, or reply to typed input."""
    if update.callback_query:
        return await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    return await update.message.reply_text(text, reply_markup=reply_markup)


async def cancel_pressed(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END


async def end_on_command(update: Update, context: Context) -> int:
    """Any other command ends the wizard, so two wizards are never active at once."""
    return ConversationHandler.END


class Steps:
    """A wizard's questions, in order.

    Each ask function shows one question, with the answers given so far, and returns
    its conversation state. Answer handlers call next(); the Back button re-asks the
    previous question, so every step can go back to the one before it.
    """

    def __init__(self, draft_name: str, *asks: Ask) -> None:
        self.draft_name = draft_name
        self.asks = asks

    async def ask(self, update: Update, context: Context, index: int) -> int:
        draft(context, self.draft_name)["step"] = index
        return await self.asks[index](update, context)

    async def first(self, update: Update, context: Context) -> int:
        return await self.ask(update, context, 0)

    async def next(self, update: Update, context: Context) -> int:
        return await self.ask(update, context, self._current(context) + 1)

    async def again(self, update: Update, context: Context) -> int:
        return await self.ask(update, context, self._current(context))

    async def back(self, update: Update, context: Context) -> int:
        await update.callback_query.answer()
        context.user_data.pop(CALENDAR_KEY, None)
        return await self.ask(update, context, max(0, self._current(context) - 1))

    def _current(self, context: Context) -> int:
        return draft(context, self.draft_name).get("step", 0)


def _only_while_active(name: str, callback: Ask) -> Ask:
    """Ignore input meant for a newer wizard (the editor can start while another wizard is open)."""

    @wraps(callback)
    async def guarded(update: Update, context: Context) -> Optional[int]:
        if context.user_data.get(ACTIVE_WIZARD_KEY) != name:
            return None  # keep this wizard where it is
        return await callback(update, context)

    return guarded


def wizard_conversation(name: str, entry: BaseHandler | list[BaseHandler],
                        states: dict[int, list[BaseHandler]], on_back: Ask) -> ConversationHandler:
    """name must match the wizard's start_draft name."""
    for handlers in states.values():
        for handler in handlers:
            handler.callback = _only_while_active(name, handler.callback)
    return ConversationHandler(
        entry_points=entry if isinstance(entry, list) else [entry],
        states=states,
        fallbacks=[
            CallbackQueryHandler(cancel_pressed, pattern=f"^{CANCEL}$"),
            CallbackQueryHandler(_only_while_active(name, on_back), pattern=f"^{BACK}$"),
            MessageHandler(filters.COMMAND, end_on_command),
        ],
        allow_reentry=True,
        name=name,
    )


def run_in_background(context: Context, update: Update, coro: Coroutine[Any, Any, None]) -> asyncio.Task:
    """Long searches run as tasks so the bot keeps answering; /cancel or Stop cancels them."""
    previous = context.user_data.get(TASK_KEY)
    if previous and not previous.done():
        previous.cancel()
    task = context.application.create_task(coro, update=update)
    track_task(context.application, task)
    context.user_data[TASK_KEY] = task
    return task


def cancel_running_task(context: Context) -> bool:
    task = context.user_data.pop(TASK_KEY, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


def parse_price(text: str) -> Optional[float]:
    """A typed amount like '45', '€45.50' or '45,5'; None unless it's a finite number of at least 0."""
    try:
        value = float(text.strip().replace("€", "").replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


# ----------------------------------------------------------------------
# Airport step
# ----------------------------------------------------------------------

def airport_step(prefix: str, state: int, on_pick: OnAirport, back: bool = True,
                 on_region: Optional[Callable[[Update, Context, str], Awaitable[int]]] = None) -> list[BaseHandler]:
    """Typed city or code -> up to 4 matching airports as buttons -> on_pick(code).

    With on_region, typing a region name ('Europe') calls it instead of guessing airports.
    """

    async def typed(update: Update, context: Context) -> int:
        region = find_region(update.message.text) if on_region else None
        if region:
            return await on_region(update, context, region)
        matches = get_services(context).resolver.resolve(update.message.text)
        if not matches:
            await update.message.reply_text(
                "❌ I don't know that place. Try another city name or airport code.",
                reply_markup=markup(back=back),
            )
            return state
        await update.message.reply_text(
            "Which airport do you mean? (Or type another name.)",
            reply_markup=keyboards.airport_choices(prefix, matches[:4], back=back),
        )
        return state

    async def picked(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        return await on_pick(update, context, update.callback_query.data.rsplit(":", 1)[1])

    return [
        MessageHandler(TEXT, typed),
        CallbackQueryHandler(picked, pattern=rf"^{prefix}:[A-Z]{{3}}$"),
    ]


# ----------------------------------------------------------------------
# Date steps
# ----------------------------------------------------------------------

def dates_keyboard(prefix: str) -> InlineKeyboardMarkup:
    presets = [button(label, f"{prefix}:preset:{key}") for key, label in PRESETS.items()]
    return markup(*pairs(presets + [button("📆 Calendar", f"{prefix}:cal:open")]), back=True)


DATES_PROMPT = ("Pick a preset, open the calendar, or type a date (<code>YYYY-MM-DD</code>) "
                "or range (<code>YYYY-MM-DD..YYYY-MM-DD</code>):")


def dates_step(prefix: str, state: int, on_dates: OnDates, on_back: Ask) -> list[BaseHandler]:
    """Departure date or range from presets, the calendar, or typed text.

    on_back re-shows this step; it's what Back does from inside the calendar.
    """

    async def typed(update: Update, context: Context) -> int:
        try:
            start, end = parse_date_or_range(update.message.text)
        except ValueError:
            await update.message.reply_text(
                "❌ I couldn't read that date. Use <code>YYYY-MM-DD</code> or <code>YYYY-MM-DD..YYYY-MM-DD</code>.",
                reply_markup=markup(back=True),
            )
            return state
        problem = window_problem(start, end)
        if problem:
            await update.message.reply_text(f"❌ {problem}", reply_markup=markup(back=True))
            return state
        return await on_dates(update, context, start, end)

    async def preset(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        start, end = get_preset_range(update.callback_query.data.rsplit(":", 1)[1])
        return await on_dates(update, context, start, end)

    return [
        MessageHandler(TEXT, typed),
        CallbackQueryHandler(preset, pattern=rf"^{prefix}:preset:({'|'.join(PRESETS)})$"),
        *calendar_handlers(f"{prefix}:cal", state, on_dates, on_back),
    ]


def timeframe_keyboard(prefix: str, day_options: list[int], default: int = 30) -> InlineKeyboardMarkup:
    labels = [f"{days} Days (Default)" if days == default else f"{days} Days" for days in day_options]
    day_buttons = [button(label, f"{prefix}:days:{days}") for label, days in zip(labels, day_options)]
    return markup(*pairs(day_buttons), [button("📆 Calendar", f"{prefix}:cal:open")], back=True)


def timeframe_step(prefix: str, state: int, on_days: OnDays, on_dates: OnDates, on_back: Ask) -> list[BaseHandler]:
    """How far ahead to look (typed or button), or specific dates from the calendar."""

    async def typed(update: Update, context: Context) -> int:
        text = update.message.text.strip()
        if not text.isdigit() or not 1 <= int(text) <= MAX_RANGE_DAYS:
            await update.message.reply_text(
                f"❌ Type a number of days between 1 and {MAX_RANGE_DAYS}, or tap a button.",
                reply_markup=markup(back=True),
            )
            return state
        return await on_days(update, context, int(text))

    async def picked(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        return await on_days(update, context, int(update.callback_query.data.rsplit(":", 1)[1]))

    return [
        MessageHandler(TEXT, typed),
        CallbackQueryHandler(picked, pattern=rf"^{prefix}:days:\d+$"),
        *calendar_handlers(f"{prefix}:cal", state, on_dates, on_back),
    ]


def calendar_handlers(prefix: str, state: int, on_dates: OnDates, on_close: Ask) -> list[BaseHandler]:
    """Open, navigate, switch single/range mode, pick days, or close (Back) the date picker."""

    def picker(context: Context) -> dict[str, Any]:
        return context.user_data.setdefault(CALENDAR_KEY, {"mode": RANGE, "start": None, "month": None})

    def render(context: Context) -> InlineKeyboardMarkup:
        cal = picker(context)
        year, month = (int(part) for part in cal["month"].split("-"))
        start = date.fromisoformat(cal["start"]) if cal["start"] else None
        return calendar_markup(prefix, year, month, today_local(), mode=cal["mode"], range_start=start,
                               back_data=f"{prefix}:close")

    async def open_picker(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        today = today_local()
        context.user_data[CALENDAR_KEY] = {"mode": RANGE, "start": None, "month": f"{today:%Y-%m}"}
        await respond(update, "📆 Pick the first day of the range (or switch to one day):", render(context))
        return state

    async def navigate(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        picker(context)["month"] = update.callback_query.data.rsplit(":", 1)[1]
        await update.callback_query.edit_message_reply_markup(render(context))
        return state

    async def switch_mode(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        cal = picker(context)
        cal["mode"] = update.callback_query.data.rsplit(":", 1)[1]
        cal["start"] = None
        prompt = "📆 Pick the departure date:" if cal["mode"] == SINGLE else "📆 Pick the first day of the range:"
        await respond(update, prompt, render(context))
        return state

    async def pick_day(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        cal = picker(context)
        day = update.callback_query.data.rsplit(":", 1)[1]
        if cal["mode"] == RANGE and not cal["start"]:
            cal["start"] = day
            cal["month"] = day[:7]
            await respond(update, f"📆 Start: <b>{day}</b>. Now pick the last day (tap it again for a single day):",
                          render(context))
            return state
        start, end = sorted([cal["start"] or day, day])
        end = end if end != start else None
        problem = window_problem(start, end)
        if problem:
            cal["start"] = None
            await respond(update, f"❌ {problem} Pick the first day again:", render(context))
            return state
        context.user_data.pop(CALENDAR_KEY, None)
        return await on_dates(update, context, start, end)

    async def close(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        context.user_data.pop(CALENDAR_KEY, None)
        return await on_close(update, context)

    return [
        CallbackQueryHandler(open_picker, pattern=rf"^{prefix}:open$"),
        CallbackQueryHandler(close, pattern=rf"^{prefix}:close$"),
        CallbackQueryHandler(navigate, pattern=rf"^{prefix}:nav:\d{{4}}-\d{{2}}$"),
        CallbackQueryHandler(switch_mode, pattern=rf"^{prefix}:mode:({SINGLE}|{RANGE})$"),
        CallbackQueryHandler(pick_day, pattern=rf"^{prefix}:day:\d{{4}}-\d{{2}}-\d{{2}}$"),
    ]


# ----------------------------------------------------------------------
# Choice step
# ----------------------------------------------------------------------

def choice_step(prefix: str, on_choice: Callable[[Update, Context, str], Awaitable[int]],
                values: str = r"[A-Za-z0-9_:]+") -> CallbackQueryHandler:
    """A plain button press: '<prefix>:<value>' -> on_choice(value)."""

    async def chosen(update: Update, context: Context) -> int:
        await update.callback_query.answer()
        return await on_choice(update, context, update.callback_query.data[len(prefix) + 1:])

    return CallbackQueryHandler(chosen, pattern=rf"^{prefix}:({values})$")
