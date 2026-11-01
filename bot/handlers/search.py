"""/search wizard and shortcut."""
import asyncio
import logging
from html import escape
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler

from bot.delivery import deliver
from bot.formatting import (
    GOOGLE_UNREACHABLE, failed_searches_note, flight_type_label, offers_block, progress_text, query_scope,
    short_window,
)
from bot.lifecycle import RESTART_NOTICE
from bot.keyboards import (
    EXPLORE_FROM_SEARCH, button, explore_from_search_prefix, flight_types, markup, regions, stop_markup,
    track_button_data,
)
from bot.auth import max_range_days
from bot.services import Services, get_services
from bot.wizard import (
    DATES_PROMPT, DIRECT_WORDS, Context, airport_step, choice_step, dates_keyboard, dates_step, draft, origin_question,
    remember_origin, respond, Steps, run_in_background, start_draft, wizard_conversation,
)
from providers.base import FlightSearchError
from providers.fast_flights import build_google_flights_url
from providers.slots import search_job
from services.airports_data import region_display_name
from services.progress import Progress
from utils.date_parser import describe_window, generate_date_sequence, parse_date_or_range, window_problem

logger = logging.getLogger(__name__)

ORIGIN, DESTINATION, DATES, FLIGHT_TYPE = range(4)
DRAFT = "search"
TOP_RESULTS = 5
USAGE = ("Usage: <code>/search ATH LON 2026-09-01</code>\n"
         "or a range, direct flights only: <code>/search ATH LON 2026-09-01..2026-09-15 direct</code>")


async def start(update: Update, context: Context) -> int:
    if context.args:
        await _shortcut(update, context, context.args)
        return ConversationHandler.END
    start_draft(context, DRAFT)
    return await STEPS.first(update, context)


async def _shortcut(update: Update, context: Context, args: list[str]) -> None:
    if len(args) < 3:
        await update.message.reply_text(USAGE)
        return
    resolver = get_services(context).resolver
    origin, destination = resolver.best_guess(args[0]), resolver.best_guess(args[1])
    if not origin or not destination:
        unknown = args[0] if not origin else args[1]
        await update.message.reply_text(f"❌ I don't know '{escape(unknown)}'. Type a city or airport name, or a code like ATH.")
        return
    try:
        start_date, end_date = parse_date_or_range(args[2])
    except ValueError:
        await update.message.reply_text(f"❌ I couldn't read that date.\n{USAGE}")
        return
    problem = window_problem(start_date, end_date, max_days=max_range_days(update.effective_user.id))
    if problem:
        await update.message.reply_text(f"❌ {problem}")
        return
    direct_only = len(args) > 3 and args[3].lower() in DIRECT_WORDS
    await run_search(update, context, origin, destination, start_date, end_date, direct_only)


async def ask_origin(update: Update, context: Context) -> int:
    question, buttons = await origin_question(update, context, "src:org")
    await respond(update, f"🔍 <b>Flight search</b>\n\n🛫 <b>Step 1/4</b>: {question}", buttons)
    return ORIGIN


async def ask_destination(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"🛫 <b>From</b>: {d['origin']}\n\n🛬 <b>Step 2/4</b>: Where are you flying to? "
                          "(e.g. London, LON, or a region like Europe)",
                  markup([button("🌍 Whole Region Instead", REGION_PICKER)], back=True))
    return DESTINATION


# A region as destination continues in /explore, which starts from these buttons.
REGION_PICKER = "src:regions"


async def show_region_picker(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    origin = draft(context, DRAFT)["origin"]
    await respond(update, f"🛫 <b>From</b>: {origin}\n\n🌍 Which region? I'll find the best deals across all of it.",
                  regions(explore_from_search_prefix(origin), back_data=f"{REGION_PICKER}:close"))
    return DESTINATION


async def close_region_picker(update: Update, context: Context) -> int:
    await update.callback_query.answer()
    return await STEPS.again(update, context)


async def region_typed(update: Update, context: Context, region: str) -> int:
    origin = draft(context, DRAFT)["origin"]
    await update.message.reply_text(
        f"🌍 <b>{region_display_name(region)}</b> is a whole region. Want the best deals from {origin} "
        "to every airport in it? (Or type a city instead.)",
        reply_markup=markup([button(f"🌍 Explore {region_display_name(region)}",
                                    f"{explore_from_search_prefix(origin)}:{region}")], back=True),
    )
    return DESTINATION


async def handed_to_explore(update: Update, context: Context) -> int:
    """/explore takes over from the same button press."""
    return ConversationHandler.END


async def ask_dates(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"📍 <b>Route</b>: {d['origin']} ✈️ {d['destination']}\n\n📅 <b>Step 3/4</b>: {DATES_PROMPT}",
                  dates_keyboard("src:date"))
    return DATES


async def ask_flight_type(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"📅 <b>Date</b>: {describe_window(d['start'], d['end'])}\n\n"
                          "⚙️ <b>Step 4/4</b>: Which flights do you want?", flight_types("src:direct"))
    return FLIGHT_TYPE


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
    d = draft(context, DRAFT)
    await run_search(update, context, d["origin"], d["destination"], d["start"], d["end"], value == "1")
    return ConversationHandler.END


STEPS = Steps(DRAFT, ask_origin, ask_destination, ask_dates, ask_flight_type)


async def run_search(update: Update, context: Context, origin: str, destination: str,
                     start_date: str, end_date: Optional[str], direct_only: bool) -> None:
    remember_origin(context.user_data, origin)
    dates = generate_date_sequence(start_date, end_date) if end_date else [start_date]
    header = f"🔍 <b>{origin} ✈️ {destination}</b> · {'direct only' if direct_only else 'any flights'}"
    stop = stop_markup() if len(dates) > 1 else None
    status = await respond(update, f"{header}\n📅 {short_window(start_date, end_date)}\n\n⏳ Searching…", stop)
    run_in_background(context, update, _search_and_report(
        get_services(context), status, header, stop, origin, destination, dates, direct_only))


async def _search_and_report(services: Services, status: Message, header: str,
                             stop: Optional[InlineKeyboardMarkup], origin: str, destination: str,
                             dates: list[str], direct_only: bool) -> None:
    async def show_progress(done: int, total: int, seconds: float) -> None:
        details = f"{short_window(dates[0], dates[-1])} · {query_scope(1, total)}"
        await _edit_quietly(status, progress_text(header, details, done, total, seconds), stop)

    provider = services.provider
    progress = Progress(len(dates), show_progress if len(dates) > 1 else None,
                        provider.average_latency() / provider.concurrency, estimate=provider.seconds_left)
    async def search_day(day: str) -> Optional[list]:
        try:
            return await provider.search_flights(origin=origin, destination=destination, departure_date=day,
                                                 direct_only=direct_only)
        except FlightSearchError:
            return None

    try:
        with search_job(f"search {origin}-{destination}", interactive=True):  # someone is waiting: goes first
            await progress.start()
            batches = await asyncio.gather(*(progress.track(search_day(day)) for day in dates))
    except asyncio.CancelledError:
        await _edit_quietly(status, RESTART_NOTICE if services.shutting_down else "⏹ Search stopped.")
        raise

    failed = sum(1 for batch in batches if batch is None)
    bot, chat_id = status.get_bot(), status.chat_id
    if failed == len(dates):
        await deliver(bot, chat_id, status, [f"{header}\n\n{GOOGLE_UNREACHABLE}"])
        return
    offers = [offer for batch in batches if batch for offer in batch]
    end_date = dates[-1] if len(dates) > 1 else None
    text, keyboard = search_results(origin, destination, dates[0], end_date, direct_only, offers)
    note = failed_searches_note(failed, len(dates), "days")
    await deliver(bot, chat_id, status, [text + (f"\n\n{note}" if note else "")], keyboard)


def search_results(origin: str, destination: str, start_date: str, end_date: Optional[str],
                   direct_only: bool, offers: list) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Results text and keyboard: link to the best offer and a button to track it."""
    dates = describe_window(start_date, end_date)
    if not offers:
        return (f"❌ No flights found for <b>{origin} ✈️ {destination}</b> on <b>{dates}</b> "
                f"({flight_type_label(direct_only).lower()}).", None)

    top = sorted(offers, key=lambda o: o.price)[:TOP_RESULTS]
    lowest = top[0]
    text = "\n".join([
        f"✈️ <b>Top {len(top)} flights</b> ({flight_type_label(direct_only)})",
        f"📍 <b>Route</b>: {origin} ✈️ {destination} | 📅 <b>Date</b>: {dates}",
        "",
        offers_block(top, show_date=bool(end_date), direct_only=direct_only, searched=(origin, destination)),
    ])
    best_url = lowest.booking_url or build_google_flights_url(origin, destination, lowest.departure_date,
                                                             direct_only=direct_only)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=best_url)],
        [button(f"🔔 Track This Route (budget €{lowest.price:.2f})",
                track_button_data(origin, destination, start_date, end_date, lowest.price, direct_only))],
    ])
    return text, keyboard


async def _edit_quietly(message: Message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except BadRequest:
        logger.debug("Could not edit search status message", exc_info=True)


def conversation() -> ConversationHandler:
    return wizard_conversation("search", CommandHandler("search", start), {
        ORIGIN: airport_step("src:org", ORIGIN, origin_picked, back=False),
        DESTINATION: [
            *airport_step("src:dst", DESTINATION, destination_picked, on_region=region_typed),
            CallbackQueryHandler(show_region_picker, pattern=f"^{REGION_PICKER}$"),
            CallbackQueryHandler(close_region_picker, pattern=f"^{REGION_PICKER}:close$"),
            CallbackQueryHandler(handed_to_explore, pattern=EXPLORE_FROM_SEARCH),
        ],
        DATES: dates_step("src:date", DATES, dates_picked, STEPS.again),
        FLIGHT_TYPE: [choice_step("src:direct", flight_type_picked, "0|1")],
    }, STEPS.back)
