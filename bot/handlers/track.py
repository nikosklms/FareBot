"""/track wizard, plus the 'Track' buttons on search and explore results."""
import re
from datetime import date
from html import escape
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler

from bot.formatting import eur, flight_type_label
from bot.keyboards import TRACK_ADD, button, flight_types, markup
from bot.auth import limit_reached, max_active, max_range_days
from bot.services import get_services
from bot.wizard import (
    DATES_PROMPT, DIRECT_WORDS, TEXT, Context, airport_step, choice_step, dates_keyboard, dates_step, draft, origin_question,
    remember_origin, respond, Steps, parse_price, start_draft, wizard_conversation,
)
from config import MIN_POLL_INTERVAL_HOURS
from daemon.scheduler import schedule_tracker
from database.models import Tracker
from utils.date_parser import describe_window, parse_date_or_range, window_problem

ORIGIN, DESTINATION, DATES, FLIGHT_TYPE, BUDGET, FREQUENCY = range(6)
DRAFT = "track"
# What a Track button on search or explore results carries (see keyboards.track_button_data).
TRACK_BUTTON = re.compile(rf"^{TRACK_ADD}:([A-Z]{{3}}):([A-Z]{{3}}):(\d{{4}}-\d{{2}}-\d{{2}}):(\d{{4}}-\d{{2}}-\d{{2}})?:"
                          r"(\d+(?:\.\d{1,2})?):([01])$")
FREQUENCIES = [h for h in (6, 12, 24) if h >= MIN_POLL_INTERVAL_HOURS]
USAGE = ("Usage: <code>/track ATH LON 2026-09-01 150</code> (150 is your budget in €)\n"
         "or a range, direct flights only: <code>/track ATH LON 2026-09-01..2026-09-15 150 direct</code>")


class TrackerRejected(Exception):
    """Creating the tracker was refused; the message explains why."""

    def __init__(self, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None):
        super().__init__(text)
        self.text = text
        self.reply_markup = reply_markup


async def create_tracker_for_user(
    context: Context,
    user_id: int,
    origin: str,
    destination: str,
    start: str,
    end: Optional[str],
    max_budget: float,
    frequency_hours: int = 6,
    direct_only: bool = False,
) -> Tracker:
    """The one place trackers are created: enforces the limit and refuses duplicates."""
    services = get_services(context)
    if await services.db.count_active(user_id) >= max_active(user_id):
        raise TrackerRejected(limit_reached(user_id))
    existing = await services.db.find_tracker(user_id, origin, destination, start, end, direct_only)
    if existing:
        raise TrackerRejected(
            f"ℹ️ You're already tracking <b>{origin} ✈️ {destination}</b> on <b>{describe_window(start, end)}</b> "
            f"(Tracker #{existing.id}, budget {eur(existing.max_budget)}).",
            InlineKeyboardMarkup([[button("✏️ Edit Its Budget", f"dash:budget:t:{existing.id}")]]),
        )
    tracker = await services.db.create_tracker(
        user_id=user_id, origin_code=origin, destination_code=destination,
        departure_date=start, departure_date_end=end, max_budget=max_budget,
        frequency_hours=frequency_hours, direct_only=direct_only,
    )
    schedule_tracker(context.job_queue, tracker)
    remember_origin(context.user_data, origin)
    return tracker


def tracker_created_text(tracker: Tracker, note: str = "") -> str:
    return "\n".join([
        f"✅ <b>Tracking started!</b> (Tracker #{tracker.id})",
        "",
        f"📍 <b>Route</b>: {tracker.origin_code} ✈️ {tracker.destination_code}",
        f"📅 <b>Date</b>: {describe_window(tracker.departure_date, tracker.departure_date_end)}",
        f"⚙️ <b>Flights</b>: {flight_type_label(tracker.direct_only)}",
        f"🎯 <b>Target budget</b>: {eur(tracker.max_budget)}{note}",
        f"🔄 <b>Checks</b>: every {tracker.frequency_hours} hours",
        "",
        "I'll message you as soon as a price drops below your budget.",
    ])


async def track_button_pressed(update: Update, context: Context) -> None:
    """'Track' button on search or explore results."""
    query = update.callback_query
    # Button data comes from the user's Telegram app, so check it like typed input.
    match = TRACK_BUTTON.match(query.data)
    origin, destination, start, end, budget, direct = match.groups() if match else (None,) * 6
    problem = "This button doesn't work."
    if match and float(budget) > 0:
        try:
            for day in (start, end):
                if day:
                    date.fromisoformat(day)  # rejects impossible dates like 2026-02-31
            problem = window_problem(start, end, max_days=max_range_days(query.from_user.id))
            if end and end <= start:
                problem = "This button doesn't work."
        except ValueError:
            pass
    if problem:
        await query.answer(problem, show_alert=True)
        return
    try:
        tracker = await create_tracker_for_user(
            context, query.from_user.id, origin, destination, start, end or None,
            float(budget), direct_only=direct == "1",
        )
    except TrackerRejected as rejected:
        await query.answer()
        await query.message.reply_text(rejected.text, reply_markup=rejected.reply_markup)
        return
    await query.answer("✅ Tracking started")
    await query.message.reply_text(tracker_created_text(tracker))


# ----------------------------------------------------------------------
# Wizard
# ----------------------------------------------------------------------

async def start(update: Update, context: Context) -> int:
    if context.args:
        await _shortcut(update, context, context.args)
        return ConversationHandler.END
    start_draft(context, DRAFT)
    return await STEPS.first(update, context)


async def _shortcut(update: Update, context: Context, args: list[str]) -> None:
    if len(args) < 4:
        await update.message.reply_text(USAGE)
        return
    resolver = get_services(context).resolver
    origin, destination = resolver.best_guess(args[0]), resolver.best_guess(args[1])
    if not origin or not destination:
        unknown = args[0] if not origin else args[1]
        await update.message.reply_text(f"❌ I don't know '{escape(unknown)}'. Type a city or airport name, or a code like ATH.")
        return
    budget = parse_price(args[3])
    try:
        start_date, end_date = parse_date_or_range(args[2])
    except ValueError:
        budget = None
    if budget is None:
        await update.message.reply_text(f"❌ I couldn't read the date or budget.\n{USAGE}")
        return
    problem = (window_problem(start_date, end_date, max_days=max_range_days(update.effective_user.id))
               or (None if budget > 0 else "The budget must be above 0."))
    if problem:
        await update.message.reply_text(f"❌ {problem}")
        return
    direct_only = len(args) > 4 and args[4].lower() in DIRECT_WORDS
    try:
        tracker = await create_tracker_for_user(
            context, update.effective_user.id, origin, destination,
            start_date, end_date, budget, direct_only=direct_only,
        )
    except TrackerRejected as rejected:
        await update.message.reply_text(rejected.text, reply_markup=rejected.reply_markup)
        return
    await update.message.reply_text(tracker_created_text(tracker))


async def ask_origin(update: Update, context: Context) -> int:
    question, buttons = await origin_question(update, context, "trk:org")
    await respond(update, f"🔔 <b>New price tracker</b>\n\n🛫 <b>Step 1/6</b>: {question}", buttons)
    return ORIGIN


async def ask_destination(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"🛫 <b>From</b>: {d['origin']}\n\n🛬 <b>Step 2/6</b>: Where are you flying to? "
                          "(e.g. London, LON)", markup(back=True))
    return DESTINATION


async def ask_dates(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"📍 <b>Route</b>: {d['origin']} ✈️ {d['destination']}\n\n📅 <b>Step 3/6</b>: {DATES_PROMPT}",
                  dates_keyboard("trk:date"))
    return DATES


async def ask_flight_type(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"📅 <b>Date</b>: {describe_window(d['start'], d['end'])}\n\n"
                          "⚙️ <b>Step 4/6</b>: Which flights should I watch?", flight_types("trk:direct"))
    return FLIGHT_TYPE


async def ask_budget(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"⚙️ <b>Flights</b>: {flight_type_label(d['direct_only'])}\n\n"
                          "💶 <b>Step 5/6</b>: What's your maximum price in EUR? (e.g. <code>150</code>)",
                  markup(back=True))
    return BUDGET


async def ask_frequency(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    hours = markup(*[[button(f"Every {h} hours", f"trk:freq:{h}")] for h in FREQUENCIES], back=True)
    await respond(update, f"🎯 <b>Budget</b>: {eur(d['budget'])}\n\n⏰ <b>Step 6/6</b>: How often should I check?",
                  hours)
    return FREQUENCY


async def origin_picked(update: Update, context: Context, code: str) -> int:
    draft(context, DRAFT)["origin"] = code
    return await STEPS.next(update, context)


async def destination_picked(update: Update, context: Context, code: str) -> int:
    draft(context, DRAFT)["destination"] = code
    return await STEPS.next(update, context)


async def dates_picked(update: Update, context: Context, start_date: str, end_date: Optional[str]) -> int:
    d = draft(context, DRAFT)
    d["start"], d["end"] = start_date, end_date
    return await STEPS.next(update, context)


async def flight_type_picked(update: Update, context: Context, value: str) -> int:
    draft(context, DRAFT)["direct_only"] = value == "1"
    return await STEPS.next(update, context)


async def budget_typed(update: Update, context: Context) -> int:
    budget = parse_price(update.message.text) or 0
    if budget <= 0:
        await update.message.reply_text("❌ Type a price above 0, e.g. <code>150</code>.", reply_markup=markup(back=True))
        return BUDGET
    draft(context, DRAFT)["budget"] = budget
    return await STEPS.next(update, context)


async def frequency_picked(update: Update, context: Context, value: str) -> int:
    d = draft(context, DRAFT)
    try:
        tracker = await create_tracker_for_user(
            context, update.effective_user.id, d["origin"], d["destination"], d["start"], d["end"],
            d["budget"], frequency_hours=int(value), direct_only=d["direct_only"],
        )
    except TrackerRejected as rejected:
        await respond(update, rejected.text, rejected.reply_markup)
        return ConversationHandler.END
    await respond(update, tracker_created_text(tracker))
    return ConversationHandler.END


STEPS = Steps(DRAFT, ask_origin, ask_destination, ask_dates, ask_flight_type, ask_budget, ask_frequency)


def conversation() -> ConversationHandler:
    return wizard_conversation("track", CommandHandler("track", start), {
        ORIGIN: airport_step("trk:org", ORIGIN, origin_picked, back=False),
        DESTINATION: airport_step("trk:dst", DESTINATION, destination_picked),
        DATES: dates_step("trk:date", DATES, dates_picked, STEPS.again),
        FLIGHT_TYPE: [choice_step("trk:direct", flight_type_picked, "0|1")],
        BUDGET: [MessageHandler(TEXT, budget_typed)],
        FREQUENCY: [choice_step("trk:freq", frequency_picked, "|".join(map(str, FREQUENCIES)))],
    }, STEPS.back)


track_button_handler = CallbackQueryHandler(track_button_pressed, pattern=rf"^{TRACK_ADD}:")
