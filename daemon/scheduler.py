"""Background jobs: tracker price checks, weekly digests and nightly cleanup."""
import asyncio
import logging
from datetime import time, tzinfo
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes, JobQueue

from bot.formatting import (
    budget_text, deal_report, digest_window_text, eur, flight_type_label, offers_block, progress_text,
    query_scope, short_window, split_message,
)
from bot.deal_buttons import COLLAPSED, remember_deal_buttons
from bot.keyboards import button
from bot.lifecycle import track_task
from bot.services import Services, get_services
from config import MAX_CONSECUTIVE_FAILURES
from database.models import ACTIVE, EXPIRED, PAUSED, Digest, Tracker
from providers.fast_flights import build_google_flights_url
from services.airports_data import region_display_name
from services.explore_engine import find_deals, rank_deals
from utils.date_parser import describe_window, is_past, today_utc

logger = logging.getLogger(__name__)

# python-telegram-bot numbers weekdays from Sunday = 0.
PTB_WEEKDAYS = {"Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6}
STARTUP_STAGGER_SECONDS = 20


def tracker_job_name(tracker_id: int) -> str:
    return f"tracker_job_{tracker_id}"


def digest_job_name(digest_id: int) -> str:
    return f"digest_job_{digest_id}"


def _remove_jobs(job_queue: Optional[JobQueue], name: str) -> None:
    if job_queue:
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()


def schedule_tracker(job_queue: Optional[JobQueue], tracker: Tracker, first_seconds: float = 10) -> None:
    if not job_queue:
        return
    _remove_jobs(job_queue, tracker_job_name(tracker.id))
    job_queue.run_repeating(
        tracker_job,
        interval=tracker.frequency_hours * 3600,
        first=first_seconds,
        data=tracker.id,
        name=tracker_job_name(tracker.id),
    )


def unschedule_tracker(job_queue: Optional[JobQueue], tracker_id: int) -> None:
    _remove_jobs(job_queue, tracker_job_name(tracker_id))


def schedule_digest(job_queue: Optional[JobQueue], digest: Digest, tz: tzinfo) -> None:
    if not job_queue:
        return
    _remove_jobs(job_queue, digest_job_name(digest.id))
    hour, minute = (int(part) for part in digest.delivery_time.split(":"))
    job_queue.run_daily(
        digest_job,
        time=time(hour, minute, tzinfo=tz),
        days=(PTB_WEEKDAYS[digest.delivery_day],),
        data=digest.id,
        name=digest_job_name(digest.id),
        user_id=digest.user_id,
        chat_id=digest.user_id,
    )


def unschedule_digest(job_queue: Optional[JobQueue], digest_id: int) -> None:
    _remove_jobs(job_queue, digest_job_name(digest_id))


async def register_jobs(application: Application) -> None:
    """Schedule every active tracker and digest at startup, spreading out the first checks."""
    services: Services = application.bot_data["services"]
    trackers = await services.db.active_trackers()
    for index, tracker in enumerate(trackers):
        schedule_tracker(application.job_queue, tracker, first_seconds=10 + index * STARTUP_STAGGER_SECONDS)
    digests = await services.db.active_digests()
    for digest in digests:
        schedule_digest(application.job_queue, digest, services.timezone)
    application.job_queue.run_daily(cleanup_job, time=time(0, 0, tzinfo=services.timezone), name="daily_cleanup")
    logger.info("Scheduled %d trackers and %d digests", len(trackers), len(digests))


# ----------------------------------------------------------------------
# Trackers
# ----------------------------------------------------------------------

async def tracker_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    track_task(context.application)
    try:
        keep_running = await check_tracker(get_services(context), context.bot, context.job.data)
    except asyncio.CancelledError:
        return  # shutting down; the next start checks it again
    if not keep_running:
        context.job.schedule_removal()


async def check_tracker(services: Services, bot: Bot, tracker_id: int) -> bool:
    """Check one tracker's price. Returns False when it no longer needs polling."""
    db = services.db
    tracker = await db.get_tracker(tracker_id)
    if not tracker or tracker.status != ACTIVE:
        return False

    route = f"<b>{tracker.origin_code} ✈️ {tracker.destination_code}</b>"
    dates = describe_window(tracker.departure_date, tracker.departure_date_end)

    if is_past(tracker.last_departure_date):
        await db.set_tracker_status(tracker.id, EXPIRED)
        await _notify(services, bot, tracker, f"ℹ️ Your tracker for {route} on <b>{dates}</b> expired: the departure date has passed.")
        return False

    if tracker.departure_date_end:
        offers = await services.provider.search_flights_range(
            origin=tracker.origin_code, destination=tracker.destination_code,
            start_date=tracker.departure_date, end_date=tracker.departure_date_end,
            direct_only=tracker.direct_only,
        )
    else:
        offers = await services.provider.search_flights(
            origin=tracker.origin_code, destination=tracker.destination_code,
            departure_date=tracker.departure_date, direct_only=tracker.direct_only,
        )

    if not offers:
        failures = await db.record_failure(tracker.id)
        if failures >= MAX_CONSECUTIVE_FAILURES:
            await db.set_tracker_status(tracker.id, PAUSED)
            await _notify(services, bot, tracker,
                          f"⚠️ I couldn't get prices for {route} after {failures} attempts, so the tracker is paused. "
                          "Resume it from /mytracks.")
            return False
        return True

    offers.sort(key=lambda o: o.price)
    top = offers[:5]
    lowest = top[0]
    await db.record_price(tracker.id, lowest.price, lowest.airline)
    logger.info("[TRACKER] #%d %s -> %s lowest %s (budget %s)", tracker.id, tracker.origin_code,
                tracker.destination_code, eur(lowest.price), eur(tracker.max_budget))
    if lowest.price > tracker.max_budget:
        return True

    await db.set_tracker_status(tracker.id, PAUSED)
    text = "\n".join([
        "🚨 <b>PRICE DROP ALERT!</b> 🚨",
        "",
        f"📍 <b>Route</b>: {route}",
        f"📅 <b>Date</b>: {dates}",
        f"🎯 <b>Target budget</b>: {eur(tracker.max_budget)}",
        f"⚙️ <b>Flights</b>: {flight_type_label(tracker.direct_only)}",
        "",
        f"✈️ <b>Top {len(top)} offers:</b>",
        offers_block(top, show_date=bool(tracker.departure_date_end), direct_only=tracker.direct_only),
        "",
        "The tracker is paused so you don't get repeat alerts. Set a lower budget to keep watching.",
    ])
    best_url = lowest.booking_url or build_google_flights_url(
        lowest.origin, lowest.destination, lowest.departure_date, direct_only=tracker.direct_only)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=best_url)],
        [button("✏️ Set Lower Budget", f"dash:budget:t:{tracker.id}"), button("🗑️ Delete", f"dash:del:t:{tracker.id}")],
    ])
    await _notify(services, bot, tracker, text, buttons)
    return False


async def _notify(services: Services, bot: Bot, tracker: Tracker, text: str,
                  reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await bot.send_message(chat_id=tracker.user_id, text=text, reply_markup=reply_markup)
    except Forbidden:
        logger.warning("User %s blocked the bot; pausing tracker #%d", tracker.user_id, tracker.id)
        await services.db.set_tracker_status(tracker.id, PAUSED)
    except TelegramError:
        logger.exception("Failed to send tracker #%d notification", tracker.id)


# ----------------------------------------------------------------------
# Digests
# ----------------------------------------------------------------------

async def digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    track_task(context.application)
    try:
        keep_running = await send_digest(get_services(context), context.bot, context.job.data, context.user_data)
    except asyncio.CancelledError:
        return  # shutting down; send_digest already told the user
    if not keep_running:
        context.job.schedule_removal()


async def send_digest(services: Services, bot: Bot, digest_id: int, user_data: Optional[dict] = None) -> bool:
    """Run one digest and send the report. Returns False when it no longer needs scheduling.

    With user_data, the report ends with a 'Track a deal' button that expands into per-deal buttons.
    """
    digest = await services.db.get_digest(digest_id)
    if not digest or digest.status != ACTIVE:
        return False

    region = region_display_name(digest.region)
    title = f"🗞️ <b>Weekly Flight Digest: {digest.origin_code} → {region}</b>"
    start, end = digest.window(today_utc())
    if is_past(end or start):
        await services.db.set_digest_status(digest.id, EXPIRED)
        await _send(bot, digest.user_id, f"{title}\n\nℹ️ The travel dates for this digest have passed, so it has been stopped.")
        return False
    if is_past(start):
        start = today_utc().isoformat()

    status = await _send(bot, digest.user_id, f"{title}\n\n⏳ Searching deals for {digest_window_text(digest)}…")

    when = short_window(start, end)

    async def progress(done: int, total: int, seconds: float, airports: int, days: int) -> None:
        await _edit(status, progress_text(title, f"{when} · {query_scope(airports, days)}", done, total, seconds))

    try:
        deals = await find_deals(services.provider, digest.origin_code, digest.region, start, end,
                                 max_budget=digest.max_budget, on_progress=progress)
    except asyncio.CancelledError:
        await _edit(status, f"{title}\n\n⏹ This week's digest was interrupted because the bot restarted. "
                            f"It runs again next {digest.delivery_day} at {digest.delivery_time}.")
        raise
    sections = rank_deals(deals, digest.sort_mode, digest.max_results, digest.region)
    if not sections:
        text = (f"{title}\n\nℹ️ No deals found this week (budget: {budget_text(digest.max_budget)}).\n"
                "You can change the budget in /mytracks.")
        if not await _edit(status, text):
            await _send(bot, digest.user_id, text)
        return True

    chunks = split_message(deal_report(f"{title}\n📅 {when}", sections))
    track_markup = COLLAPSED if user_data is not None else None
    last_message = None
    for index, chunk in enumerate(chunks):
        reply_markup = track_markup if index == len(chunks) - 1 else None
        last_message = await _edit(status, chunk, reply_markup) if index == 0 else None
        if not last_message:
            last_message = await _send(bot, digest.user_id, chunk, reply_markup)
    if user_data is not None and last_message:
        remember_deal_buttons(user_data, last_message.message_id, sections)
    return True


async def _send(bot: Bot, chat_id: int, text: str,
                reply_markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
    try:
        return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except TelegramError:
        logger.exception("Failed to send digest message to %s", chat_id)
        return None


async def _edit(message: Optional[Message], text: str,
                reply_markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
    """The edited message, or None if it couldn't be edited."""
    if not message:
        return None
    try:
        edited = await message.edit_text(text, reply_markup=reply_markup)
        return edited if isinstance(edited, Message) else message
    except BadRequest as e:
        return message if "not modified" in str(e) else None
    except TelegramError:
        logger.warning("Failed to edit digest message", exc_info=True)
        return None


# ----------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------

async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = await get_services(context).db.purge_stale()
    logger.info("Daily cleanup: %d expired, %d purged", stats["expired"], stats["purged"])
