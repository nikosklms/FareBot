"""/search wizard and shortcut."""
import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ConversationHandler

from bot.formatting import flight_type_label, offers_block, progress_text, query_scope, short_window
from bot.lifecycle import RESTART_NOTICE
from bot.keyboards import button, flight_types, markup, stop_markup, track_button_data
from bot.services import Services, get_services
from bot.wizard import (
    DATES_PROMPT, Context, airport_step, choice_step, dates_keyboard, dates_step, draft, respond,
    Steps, run_in_background, start_draft, wizard_conversation,
)
from providers.fast_flights import build_google_flights_url
from services.progress import Progress
from utils.date_parser import describe_window, generate_date_sequence, is_past, parse_date_or_range

logger = logging.getLogger(__name__)

ORIGIN, DESTINATION, DATES, FLIGHT_TYPE = range(4)
DRAFT = "search"
TOP_RESULTS = 5
USAGE = "Usage: <code>/search ATH LON 2026-09-01[..2026-09-15] [direct]</code>"


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
    origin_matches, destination_matches = resolver.resolve(args[0]), resolver.resolve(args[1])
    if not origin_matches or not destination_matches:
        unknown = args[0] if not origin_matches else args[1]
        await update.message.reply_text(f"❌ I don't know '{unknown}'.")
        return
    try:
        start_date, end_date = parse_date_or_range(args[2])
    except ValueError:
        await update.message.reply_text(f"❌ I couldn't read that date.\n{USAGE}")
        return
    if is_past(start_date):
        await update.message.reply_text("❌ That date is in the past.")
        return
    direct_only = len(args) > 3 and args[3].lower() in ("direct", "-d", "--direct")
    await run_search(update, context, origin_matches[0][0], destination_matches[0][0], start_date, end_date, direct_only)


async def ask_origin(update: Update, context: Context) -> int:
    await respond(update, "🔍 <b>Flight search</b>\n\n🛫 <b>Step 1/4</b>: Where are you flying from? "
                          "(e.g. Athens, ATH)", markup())
    return ORIGIN


async def ask_destination(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"🛫 <b>From</b>: {d['origin']}\n\n🛬 <b>Step 2/4</b>: Where are you flying to? "
                          "(e.g. London, LON)", markup(back=True))
    return DESTINATION


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
                        provider.average_latency() / provider.concurrency)
    try:
        await progress.start()
        batches = await asyncio.gather(*(
            progress.track(provider.search_flights(origin=origin, destination=destination, departure_date=day,
                                                   direct_only=direct_only))
            for day in dates
        ))
    except asyncio.CancelledError:
        await _edit_quietly(status, RESTART_NOTICE if services.shutting_down else "⏹ Search stopped.")
        raise

    offers = [offer for batch in batches for offer in batch]
    end_date = dates[-1] if len(dates) > 1 else None
    text, keyboard = search_results(origin, destination, dates[0], end_date, direct_only, offers)
    await status.edit_text(text, reply_markup=keyboard)


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
        offers_block(top, show_date=bool(end_date), direct_only=direct_only),
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
        DESTINATION: airport_step("src:dst", DESTINATION, destination_picked),
        DATES: dates_step("src:date", DATES, dates_picked, STEPS.again),
        FLIGHT_TYPE: [choice_step("src:direct", flight_type_picked, "0|1")],
    }, STEPS.back)
