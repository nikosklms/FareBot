import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError, RetryAfter
from database.db import DatabaseManager
from providers.base import AbstractFlightProvider
from providers.fast_flights import FastFlightsProvider
from config import DB_PATH, MAX_CONSECUTIVE_FAILURES

logger = logging.getLogger(__name__)

class TrackerDaemonScheduler:
    def __init__(self, db: DatabaseManager, provider: AbstractFlightProvider):
        self.db = db
        self.provider = provider

    async def _safe_send_message(self, bot: Bot, tracker_id: int, user_id: int, text: str, reply_markup=None):
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot. Pausing tracker #{tracker_id}.")
            await self.db.update_tracker_status(tracker_id, "PAUSED")
        except RetryAfter as e:
            logger.warning(f"Telegram rate limited. Retry after {e.retry_after}s for tracker #{tracker_id}.")
        except TelegramError as e:
            logger.error(f"Telegram API error for user {user_id}: {e}")

    async def poll_tracker(self, tracker_id: int, bot: Bot):
        tracker = await self.db.get_tracker_by_id(tracker_id)
        if not tracker or tracker["status"] != "ACTIVE":
            return

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if tracker["departure_date"] < today_str:
            await self.db.update_tracker_status(tracker_id, "EXPIRED")
            await self._safe_send_message(
                bot, tracker_id, tracker["user_id"],
                f"ℹ️ Your tracker for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** on **{tracker['departure_date']}** has expired as the departure date has passed."
            )
            return

        direct_only = bool(tracker.get("direct_only", 0))
        offers = await self.provider.search_flights(
            origin=tracker["origin_code"],
            destination=tracker["destination_code"],
            departure_date=tracker["departure_date"],
            direct_only=direct_only
        )

        if not offers:
            fails = await self.db.increment_failure_count(tracker_id)
            if fails >= MAX_CONSECUTIVE_FAILURES:
                await self.db.update_tracker_status(tracker_id, "PAUSED")
                await self._safe_send_message(
                    bot, tracker_id, tracker["user_id"],
                    f"⚠️ Unable to check prices for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** after 3 attempts. Tracker paused."
                )
            return

        await self.db.reset_failure_count(tracker_id)
        lowest = min(offers, key=lambda x: x.price)
        await self.db.log_price(tracker_id, lowest.price, lowest.airline)

        if lowest.price <= tracker["max_budget"]:
            await self.db.update_tracker_status(tracker_id, "PAUSED")
            filter_badge = "Direct Flights Only ✈️" if direct_only else "Any Flights 🔄"
            stop_badge = "Direct ✈️" if lowest.is_direct else "1+ Stops 🔄"
            offset_str = f" (+{lowest.day_offset})" if getattr(lowest, "day_offset", 0) > 0 else ""
            time_line = f"\n🕒 **Flight Times**: {lowest.departure_time} ➔ {lowest.arrival_time}{offset_str}" if (lowest.departure_time and lowest.arrival_time) else ""
            alert_text = (

                "🚨 **PRICE DROP ALERT!** 🚨\n\n"
                f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}\n"
                f"📅 **Date**: {lowest.departure_date}{time_line}\n"
                f"🎯 **Target Budget**: €{tracker['max_budget']:.2f}\n"
                f"💶 **Current Price**: **€{lowest.price:.2f}** ({stop_badge})\n"
                f"🏢 **Airline**: {lowest.airline or 'Various'}\n"
                f"⚙️ **Filter**: {filter_badge}"
            )

            buttons = [
                [InlineKeyboardButton("🔗 View & Book Flight", url=lowest.booking_url or "https://www.google.com/travel/flights")],
                [InlineKeyboardButton("⏸ Keep Paused", callback_data=f"dash_pause_{tracker_id}"), InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{tracker_id}")]
            ]
            await self._safe_send_message(
                bot, tracker_id, tracker["user_id"], alert_text, InlineKeyboardMarkup(buttons)
            )


def schedule_tracker_job(
    job_queue,
    tracker_id: int,
    frequency_hours: int = 6,
    db: Optional[DatabaseManager] = None,
    provider: Optional[AbstractFlightProvider] = None
):
    """Dynamically schedule a repeating price check job for a tracker into JobQueue."""
    if not job_queue:
        return

    # Unschedule any pre-existing job with the same name first
    unschedule_tracker_job(job_queue, tracker_id)

    target_db = db or DatabaseManager(DB_PATH)
    target_provider = provider or FastFlightsProvider()
    scheduler = TrackerDaemonScheduler(target_db, target_provider)
    interval_seconds = max(frequency_hours, 1) * 3600

    async def _job_callback(context, t_id=tracker_id):
        await scheduler.poll_tracker(t_id, context.bot)

    job_queue.run_repeating(
        _job_callback,
        interval=interval_seconds,
        first=10,
        name=f"tracker_job_{tracker_id}"
    )

def unschedule_tracker_job(job_queue, tracker_id: int):
    """Remove a scheduled tracker job from JobQueue if present."""
    if not job_queue:
        return

    jobs = job_queue.get_jobs_by_name(f"tracker_job_{tracker_id}")
    if jobs:
        for job in jobs:
            job.schedule_removal()

async def register_active_trackers_on_startup(app, db: DatabaseManager, provider: AbstractFlightProvider) -> int:
    """Reload all ACTIVE trackers from SQLite into JobQueue on startup."""
    active_trackers = await db.get_active_trackers()
    count = 0

    if app.job_queue:
        for t in active_trackers:
            freq = t.get("frequency_hours", 6)
            schedule_tracker_job(app.job_queue, t["id"], freq, db=db, provider=provider)
            count += 1

    return count

def register_active_trackers(application):
    """Helper to register active background trackers on application startup."""
    db = DatabaseManager(DB_PATH)
    provider = FastFlightsProvider()

    async def _do_register():
        active_count = await register_active_trackers_on_startup(application, db, provider)
        logger.info(f"Loaded and registered {active_count} active background trackers into JobQueue.")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_register())
    except RuntimeError:
        asyncio.run(_do_register())

