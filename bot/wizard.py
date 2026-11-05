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
from bot.auth import max_range_days
from bot.date_picker import RANGE, SINGLE, calendar_markup
from bot.keyboards import BACK, CANCEL, button, markup, pairs
from bot.lifecycle import track_task
from bot.services import get_services
from services.airports_data import find_region
from utils.date_parser import PRESETS, get_preset_range, parse_date_or_range, today_local, window_problem

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
RESTART_COMMAND = {"edit": "mytracks"}  # the editor is opened from /mytracks, the others by their own command
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
    """Only the newest wizard answers (the editor can start while another wizard is open).

    A wizard that was replaced closes itself and says so on its buttons. For typed text it
    stays quiet while another wizard is answering, so the user never gets two replies.
    """

    @wraps(callback)
    async def guarded(update: Update, context: Context) -> Optional[int]:
        active = context.user_data.get(ACTIVE_WIZARD_KEY)
        if active != name:
            restart = f"Start again with /{RESTART_COMMAND.get(name, name)}."
            if update.callback_query:
                await update.callback_query.answer(f"That step was replaced by a newer one. {restart}", show_alert=True)
            elif active is None and update.message:
                await update.message.reply_text(f"That wizard was closed. {restart}")
            return ConversationHandler.END
        state = await callback(update, context)
        if state == ConversationHandler.END and context.user_data.get(ACTIVE_WIZARD_KEY) == name:
            context.user_data.pop(ACTIVE_WIZARD_KEY, None)  # finished: nothing is answering typed text now
        return state

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


DIRECT_WORDS = ("direct", "-d", "--direct")  # marks a shortcut as direct flights only
MAX_BUDGET = 100_000  # bigger amounts mean nothing for a flight, and wouldn't fit in a share link


def parse_price(text: str) -> Optional[float]:
    """A typed amount like '45', '€45.50' or '45,5'; None unless it's a number from 0 to MAX_BUDGET."""
    try:
        value = float(text.strip().replace("€", "").replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) and 0 <= value <= MAX_BUDGET else None


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


RECENT_ORIGINS_KEY = "recent_origins"
RECENT_ORIGINS = 4


def remember_origin(user_data: dict, code: str) -> None:
    """Offer this airport first next time the user picks an origin."""
    user_data[RECENT_ORIGINS_KEY] = [code, *(c for c in user_data.get(RECENT_ORIGINS_KEY, []) if c != code)]


async def origin_question(update: Update, context: Context, prefix: str) -> tuple[str, InlineKeyboardMarkup]:
    """'Where are you flying from?' with the user's recent origins as buttons: searches since
    the bot started, then their trackers and digests."""
    saved = await get_services(context).db.recent_origins(update.effective_user.id, RECENT_ORIGINS)
    codes = list(dict.fromkeys([*context.user_data.get(RECENT_ORIGINS_KEY, []), *saved]))[:RECENT_ORIGINS]
    if not codes:
        return "Where are you flying from? (e.g. Athens, ATH)", markup()
    return ("Where are you flying from? Tap a recent airport or type a city name:",
            keyboards.recent_airports(prefix, codes))


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
        limit = await max_range_days(get_services(context).db, update.effective_user.id)
        problem = window_problem(start, end, max_days=limit)
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


def timeframe_keyboard(prefix: str, day_options: list[int], default: int, max_days: int) -> InlineKeyboardMarkup:
    """Days-ahead buttons up to max_days (the user's limit), and the calendar."""
    day_options = [days for days in day_options if days <= max_days]
    labels = [f"{days} Days (Default)" if days == default else f"{days} Days" for days in day_options]
    day_buttons = [button(label, f"{prefix}:days:{days}") for label, days in zip(labels, day_options, strict=True)]
    return markup(*pairs(day_buttons), [button("📆 Calendar", f"{prefix}:cal:open")], back=True)


def timeframe_step(prefix: str, state: int, on_days: OnDays, on_dates: OnDates, on_back: Ask) -> list[BaseHandler]:
    """How far ahead to look (typed or button), or specific dates from the calendar."""

    async def typed(update: Update, context: Context) -> int:
        text = update.message.text.strip()
        limit = await max_range_days(get_services(context).db, update.effective_user.id)
        if not text.isdigit() or not 1 <= int(text) <= limit:
            await update.message.reply_text(
                f"❌ Type a number of days between 1 and {limit}, or tap a button.",
                reply_markup=markup(back=True),
            )
            return state
        return await on_days(update, context, int(text))

    async def picked(update: Update, context: Context) -> int:
        days = int(update.callback_query.data.rsplit(":", 1)[1])
        limit = await max_range_days(get_services(context).db, update.effective_user.id)
        if not 1 <= days <= limit:  # only a modified Telegram app sends other values
            await update.callback_query.answer(f"Pick between 1 and {limit} days.", show_alert=True)
            return state
        await update.callback_query.answer()
        return await on_days(update, context, days)

    return [
        MessageHandler(TEXT, typed),
        CallbackQueryHandler(picked, pattern=rf"^{prefix}:days:\d+$"),
        *calendar_handlers(f"{prefix}:cal", state, on_dates, on_back),
    ]


def calendar_handlers(prefix: str, state: int, on_dates: OnDates, on_close: Ask) -> list[BaseHandler]:
    """Open, navigate, switch single/range mode, pick days, or close (Back) the date picker."""

    def picker(context: Context) -> dict[str, Any]:
        # Buttons on an older calendar can arrive after its state was cleared; start from this month.
        return context.user_data.setdefault(CALENDAR_KEY, {"mode": RANGE, "start": None, "month": f"{today_local():%Y-%m}"})

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
        month = update.callback_query.data.rsplit(":", 1)[1]
        try:
            date.fromisoformat(f"{month}-01")
        except ValueError:
            return state  # not a real month; the buttons we send never do this
        picker(context)["month"] = month
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
        try:
            date.fromisoformat(day)
        except ValueError:
            return state  # not a real day (e.g. Feb 31); the buttons we send never do this
        if cal["mode"] == RANGE and not cal["start"]:
            cal["start"] = day
            cal["month"] = day[:7]
            await respond(update, f"📆 Start: <b>{day}</b>. Now pick the last day (tap it again for a single day):",
                          render(context))
            return state
        start, end = sorted([cal["start"] or day, day])
        end = end if end != start else None
        limit = await max_range_days(get_services(context).db, update.effective_user.id)
        problem = window_problem(start, end, max_days=limit)
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
