"""/explore wizard and shortcut: best deals from one airport to a whole region."""
import asyncio
import logging
from typing import Optional

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler

from bot.deal_buttons import COLLAPSED, remember_deal_buttons
from bot.formatting import deal_report, eur, progress_text, query_scope, short_window, split_message
from bot.lifecycle import RESTART_NOTICE
from bot.keyboards import (
    DEFAULT_RESULT_LIMIT, EXPLORE_FROM_SEARCH, markup, quick_origins, regions, result_limits, sort_modes,
    stop_markup,
)
from bot.services import Services, get_services
from bot.wizard import (
    TEXT, Context, Steps, airport_step, choice_step, draft, respond, run_in_background, start_draft,
    timeframe_keyboard, timeframe_step, wizard_conversation,
)
from services.airports_data import REGION_LABELS, region_display_name
from services.explore_engine import find_deals, rank_deals
from utils.date_parser import days_ahead_window, describe_window

logger = logging.getLogger(__name__)

ORIGIN, REGION, SORT, WINDOW, LIMIT = range(5)
DRAFT = "explore"
DAY_OPTIONS = [7, 14, 30, 60, 90]
DEFAULT_DAYS = 30
MAX_RESULTS = 20
USAGE = ("Usage: <code>/explore ATH europe [days] [budget] [results]</code>\n"
         f"Regions: {', '.join(REGION_LABELS)}")


async def start(update: Update, context: Context) -> int:
    if context.args:
        await _shortcut(update, context, context.args)
        return ConversationHandler.END
    start_draft(context, DRAFT)
    return await STEPS.first(update, context)


async def _shortcut(update: Update, context: Context, args: list[str]) -> None:
    """ORIGIN REGION [DAYS] [BUDGET] [RESULTS]"""
    region = args[1].lower() if len(args) > 1 else ""
    numbers = args[2:5]
    if region not in REGION_LABELS or not all(n.replace(".", "", 1).isdigit() for n in numbers):
        await update.message.reply_text(USAGE)
        return
    origin = get_services(context).resolver.best_guess(args[0])
    if not origin:
        await update.message.reply_text(f"❌ I don't know '{args[0]}'.")
        return
    days = int(float(numbers[0])) if numbers else DEFAULT_DAYS
    budget = float(numbers[1]) if len(numbers) > 1 else 0
    limit = int(float(numbers[2])) if len(numbers) > 2 else DEFAULT_RESULT_LIMIT
    start_date, end_date = days_ahead_window(max(1, days))
    await run_explore(update, context, origin, region, start_date, end_date, "both",
                      min(max(limit, 1), MAX_RESULTS), budget or None)


async def start_from_search(update: Update, context: Context) -> int:
    """A region picked as the destination in /search: continue here with origin and region set."""
    await update.callback_query.answer()
    _, _, origin, region = update.callback_query.data.split(":")
    d = start_draft(context, DRAFT)
    d["origin"], d["region"] = origin, region
    return await STEPS.ask(update, context, 2)


async def ask_origin(update: Update, context: Context) -> int:
    await respond(update, "🌟 <b>Explore flight deals</b>\n\n🛫 <b>Step 1/5</b>: Pick an origin airport or type a "
                          "city name:", quick_origins("exp:org"))
    return ORIGIN


async def ask_region(update: Update, context: Context) -> int:
    await respond(update, f"🛫 <b>From</b>: {draft(context, DRAFT)['origin']}\n\n🌍 <b>Step 2/5</b>: Which region?",
                  regions("exp:reg"))
    return REGION


async def ask_sort(update: Update, context: Context) -> int:
    await respond(update, f"🌍 <b>Region</b>: {region_display_name(draft(context, DRAFT)['region'])}\n\n"
                          "📊 <b>Step 3/5</b>: How should deals be ranked?", sort_modes("exp:sort"))
    return SORT


async def ask_window(update: Update, context: Context) -> int:
    await respond(update, "📅 <b>Step 4/5</b>: How far ahead should I look? Tap a button, type a number of days, "
                          "or pick dates on the calendar:", timeframe_keyboard("exp:when", DAY_OPTIONS, DEFAULT_DAYS))
    return WINDOW


async def ask_limit(update: Update, context: Context) -> int:
    d = draft(context, DRAFT)
    await respond(update, f"📅 <b>Departures</b>: {describe_window(d['start'], d['end'])}\n\n"
                          f"📊 <b>Step 5/5</b>: How many deals should I show? (1–{MAX_RESULTS})",
                  result_limits("exp:lim"))
    return LIMIT


async def origin_picked(update: Update, context: Context, code: str) -> int:
    draft(context, DRAFT)["origin"] = code
    return await STEPS.next(update, context)


async def region_picked(update: Update, context: Context, region: str) -> int:
    draft(context, DRAFT)["region"] = region
    return await STEPS.next(update, context)


async def sort_picked(update: Update, context: Context, sort_mode: str) -> int:
    draft(context, DRAFT)["sort"] = sort_mode
    return await STEPS.next(update, context)


async def days_picked(update: Update, context: Context, days: int) -> int:
    return await dates_picked(update, context, *days_ahead_window(days))


async def dates_picked(update: Update, context: Context, start_date: str, end_date: Optional[str]) -> int:
    d = draft(context, DRAFT)
    d["start"], d["end"] = start_date, end_date
    return await STEPS.next(update, context)


async def limit_picked(update: Update, context: Context, value: str) -> int:
    d = draft(context, DRAFT)
    await run_explore(update, context, d["origin"], d["region"], d["start"], d["end"], d["sort"], int(value))
    return ConversationHandler.END


async def limit_typed(update: Update, context: Context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_RESULTS:
        await update.message.reply_text(f"❌ Type a number from 1 to {MAX_RESULTS}, or tap a button.",
                                        reply_markup=markup(back=True))
        return LIMIT
    return await limit_picked(update, context, text)


STEPS = Steps(DRAFT, ask_origin, ask_region, ask_sort, ask_window, ask_limit)


async def run_explore(update: Update, context: Context, origin: str, region: str, start_date: str,
                      end_date: Optional[str], sort_mode: str, limit: int, max_budget: Optional[float] = None) -> None:
    title = f"🌟 <b>Deals from {origin} to {region_display_name(region)}</b>"
    status = await respond(update, f"{title}\n📅 {short_window(start_date, end_date)}\n\n⏳ Starting…", stop_markup())
    run_in_background(context, update, _explore_and_report(
        get_services(context), context.user_data, status, title, origin, region, start_date, end_date, sort_mode,
        limit, max_budget))


async def _explore_and_report(services: Services, user_data: dict, status: Message, title: str, origin: str,
                              region: str, start_date: str, end_date: Optional[str], sort_mode: str, limit: int,
                              max_budget: Optional[float]) -> None:
    when = short_window(start_date, end_date)
    headline = f"{title}\n📅 {when}"

    async def progress(done: int, total: int, seconds: float, airports: int, days: int) -> None:
        try:
            details = f"{when} · {query_scope(airports, days)}"
            await status.edit_text(progress_text(title, details, done, total, seconds), reply_markup=stop_markup())
        except BadRequest:
            pass

    try:
        deals = await find_deals(services.provider, origin, region, start_date, end_date,
                                 max_budget=max_budget, on_progress=progress)
    except asyncio.CancelledError:
        notice = RESTART_NOTICE if services.shutting_down else "⏹ Search stopped."
        try:
            await status.edit_text(f"{headline}\n\n{notice}")
        except BadRequest:
            pass
        raise

    sections = rank_deals(deals, sort_mode, limit, region)
    if not sections:
        budget_note = f" under {eur(max_budget)}" if max_budget else ""
        await status.edit_text(f"{headline}\n\nℹ️ No deals found{budget_note}. Try a wider date window.")
        return

    chunks = split_message(deal_report(headline, sections))
    message = status
    for index, chunk in enumerate(chunks):
        reply_markup = COLLAPSED if index == len(chunks) - 1 else None
        if index == 0:
            message = await status.edit_text(chunk, reply_markup=reply_markup)
        else:
            message = await status.reply_text(chunk, reply_markup=reply_markup)
    remember_deal_buttons(user_data, message.message_id, sections)


def conversation() -> ConversationHandler:
    return wizard_conversation("explore", [
        CommandHandler("explore", start),
        CallbackQueryHandler(start_from_search, pattern=EXPLORE_FROM_SEARCH),
    ], {
        ORIGIN: airport_step("exp:org", ORIGIN, origin_picked, back=False),
        REGION: [choice_step("exp:reg", region_picked, "|".join(REGION_LABELS))],
        SORT: [choice_step("exp:sort", sort_picked, "discount|price|both")],
        WINDOW: timeframe_step("exp:when", WINDOW, days_picked, dates_picked, STEPS.again),
        LIMIT: [choice_step("exp:lim", limit_picked, r"\d+"), MessageHandler(TEXT, limit_typed)],
    }, STEPS.back)
