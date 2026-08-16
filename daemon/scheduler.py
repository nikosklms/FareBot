import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
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

        if tracker["destination_code"].startswith("REGION:"):
            return

        logger.info(f"[TRACKER_DAEMON] Polling background tracker #{tracker_id} for user {tracker['user_id']}: {tracker['origin_code']} -> {tracker['destination_code']}")

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        end_date = tracker.get("departure_date_end") or tracker["departure_date"]
        if end_date < today_str:
            await self.db.update_tracker_status(tracker_id, "EXPIRED")
            date_display = f"{tracker['departure_date']} ➔ {end_date}" if tracker.get("departure_date_end") else tracker["departure_date"]
            await self._safe_send_message(
                bot, tracker_id, tracker["user_id"],
                f"ℹ️ Your tracker for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** on **{date_display}** has expired as the departure date has passed."
            )
            return

        direct_only = bool(tracker.get("direct_only", 0))
        if tracker.get("departure_date_end"):
            offers = await self.provider.search_flights_range(
                origin=tracker["origin_code"],
                destination=tracker["destination_code"],
                start_date=tracker["departure_date"],
                end_date=tracker["departure_date_end"],
                direct_only=direct_only
            )
        else:
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
        # Sort offers by price ascending, take top 5
        offers.sort(key=lambda x: x.price)
        top_offers = offers[:5]
        lowest = top_offers[0]
        await self.db.log_price(tracker_id, lowest.price, lowest.airline)

        if lowest.price <= tracker["max_budget"]:
            await self.db.update_tracker_status(tracker_id, "PAUSED")
            filter_badge = "Direct Flights Only ✈️" if direct_only else "Any Flights 🔄"

            from providers.fast_flights import build_google_flights_url

            date_display = f"{tracker['departure_date']} ➔ {tracker['departure_date_end']}" if tracker.get("departure_date_end") else tracker['departure_date']
            alert_lines = [
                "🚨 **PRICE DROP ALERT!** 🚨\n",
                f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}",
                f"📅 **Date**: {date_display}",
                f"🎯 **Target Budget**: €{tracker['max_budget']:.2f}",
                f"⚙️ **Filter**: {filter_badge}\n",
                f"✈️ **Top {len(top_offers)} Matching Offers:**\n"
            ]

            emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
            for i, o in enumerate(top_offers):
                stop_badge = "Direct ✈️" if o.is_direct else "1+ Stops 🔄"
                offset_str = f" (+{o.day_offset})" if getattr(o, "day_offset", 0) > 0 else ""
                time_info = f" | 🕒 {o.departure_time} ➔ {o.arrival_time}{offset_str}" if (o.departure_time and o.arrival_time) else ""
                offer_url = o.booking_url or build_google_flights_url(o.origin, o.destination, o.departure_date, direct_only=direct_only)
                date_badge = f" ({o.departure_date})" if tracker.get("departure_date_end") else ""
                price_str = f"[**€{o.price:.2f}**]({offer_url})"
                alert_lines.append(f"{emojis[i]} {price_str}{date_badge} — {o.airline or 'Various'} ({stop_badge}){time_info}")

            alert_text = "\n".join(alert_lines)

            booking_link = lowest.booking_url or build_google_flights_url(lowest.origin, lowest.destination, lowest.departure_date, direct_only=direct_only)
            buttons = [
                [InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=booking_link)],
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
    """Remove a scheduled tracker or digest job from JobQueue if present."""
    if not job_queue:
        return

    for job_name in [f"tracker_job_{tracker_id}", f"digest_job_{tracker_id}"]:
        jobs = job_queue.get_jobs_by_name(job_name)
        if jobs:
            for job in jobs:
                job.schedule_removal()

async def register_active_trackers_on_startup(app, db: DatabaseManager, provider: AbstractFlightProvider) -> int:
    """Reload all ACTIVE trackers from SQLite into JobQueue on startup."""
    active_trackers = await db.get_active_trackers()
    count = 0

    if app.job_queue:
        for t in active_trackers:
            dest = t.get("destination_code", "")
            if dest.startswith("REGION:"):
                region_name = dest.replace("REGION:", "").lower()
                schedule_digest_job(
                    app.job_queue,
                    tracker_id=t["id"],
                    user_id=t["user_id"],
                    origin=t["origin_code"],
                    region=region_name,
                    budget=t.get("max_budget"),
                    schedule_str=t.get("departure_date", "30d|Sunday@15:00")
                )
            else:
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

def calculate_next_digest_delay(schedule_str: str = "Sunday@15:00") -> float:
    """Calculate the number of seconds from now until the next occurrence of the requested weekday and time (in local time)."""
    from datetime import datetime, timedelta
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}

    target_day = "sunday"
    target_hour = 15
    target_minute = 0

    if "|" in schedule_str:
        schedule_str = schedule_str.split("|")[-1]

    if "@" in schedule_str:
        day_part, time_part = schedule_str.split("@", 1)
        target_day = day_part.strip().lower()
        if ":" in time_part:
            h_str, m_str = time_part.split(":", 1)
            if h_str.isdigit() and m_str.isdigit():
                target_hour = int(h_str)
                target_minute = int(m_str)

    target_weekday = weekdays.get(target_day, 6)
    now = datetime.now().astimezone()

    days_ahead = target_weekday - now.weekday()
    if days_ahead < 0 or (days_ahead == 0 and (now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute))):
        days_ahead += 7

    next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    delay = (next_run - now).total_seconds()
    return max(10.0, delay)

def schedule_digest_job(job_queue, tracker_id: int, user_id: int, origin: str, region: str, budget: float, schedule_str: str = "Sunday@15:00", limit: int = 10):
    """Schedule weekly recurring digest execution for user."""
    if not job_queue:
        return

    job_data = {
        "tracker_id": tracker_id,
        "user_id": user_id,
        "origin": origin,
        "region": region,
        "budget": budget,
        "schedule_str": schedule_str,
        "limit": limit
    }

    interval = 7 * 24 * 3600  # 7 days
    first_delay = calculate_next_digest_delay(schedule_str)

    job_queue.run_repeating(
        run_digest_weekly_job,
        interval=interval,
        first=first_delay,
        data=job_data,
        name=f"digest_job_{tracker_id}"
    )

async def run_digest_weekly_job(context):
    """Execute weekly digest query for user and send formatted deal report."""
    job_data = getattr(context.job, "data", {}) if hasattr(context, "job") else {}
    user_id = job_data.get("user_id")
    origin = job_data.get("origin", "ATH")
    region = job_data.get("region", "europe")
    budget = job_data.get("budget")
    limit = job_data.get("limit", 10)
    schedule_str = job_data.get("schedule_str", "30d|both|Sunday@15:00")
    offset_days = 30
    sort_mode = "both"

    if "|" in schedule_str:
        parts = schedule_str.split("|")
        if len(parts) >= 3:
            tf_part = parts[0]
            sort_mode = parts[1]
        elif len(parts) == 2:
            tf_part = parts[0]
            sort_mode = "both"
        else:
            tf_part = parts[0]

        if tf_part.endswith("d") and tf_part[:-1].isdigit():
            offset_days = int(tf_part[:-1])

    from services.explore_engine import run_explore_query, build_timeframe_date_range, render_explore_report_text

    reg_disp = region.upper().replace("_", " ")
    sent_msg = None
    if user_id and hasattr(context, "bot") and context.bot:
        try:
            init_header = f"🗞️ **Weekly Flight Digest starting for {origin} → {reg_disp}...**\n\n⏳ *Initializing deal search...*"
            sent_msg = await context.bot.send_message(chat_id=user_id, text=init_header, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send digest start message to user {user_id}: {e}")

    async def status_cb(est_seconds: float, total_queries: int, num_airports: int, num_days: int) -> None:
        if not sent_msg:
            return
        try:
            from bot.handlers.common import build_status_estimate_text
            digest_header = f"🗞️ **Weekly Flight Digest execution starting for {origin} → {reg_disp}...**"
            status_text = build_status_estimate_text(
                header_text=digest_header,
                est_seconds=est_seconds,
                total_queries=total_queries,
                num_airports=num_airports,
                num_days=num_days
            )
            await sent_msg.edit_text(status_text, parse_mode="Markdown")
        except Exception:
            pass

    dep_date = build_timeframe_date_range(offset_days)
    deals = await run_explore_query(
        origin, region, dep_date, max_budget=budget, sort_by=sort_mode, max_results=limit, status_callback=status_cb
    )

    if not user_id:
        return

    has_deals = False
    if isinstance(deals, dict):
        has_deals = bool(deals.get("discount_deals") or deals.get("cheapest_deals"))
    elif isinstance(deals, list):
        has_deals = bool(deals)

    if not has_deals:
        bud_str = f"€{budget:.2f}" if (budget and budget > 0) else "Any Budget"
        no_deals_msg = (
            f"🗞️ **Weekly Flight Digest for {origin} → {reg_disp}**\n\n"
            f"ℹ️ **No flight deals found** matching your criteria (Target Budget: {bud_str}).\n"
            f"💡 *Tip: You can edit your budget threshold anytime in `/mytracks`!*"
        )
        if sent_msg:
            try:
                await sent_msg.edit_text(text=no_deals_msg, parse_mode="Markdown")
                return
            except Exception:
                pass
        try:
            await context.bot.send_message(chat_id=user_id, text=no_deals_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send empty digest notice to user {user_id}: {e}")
        return

    msg_text = render_explore_report_text(
        origin=origin,
        region=region,
        deals=deals,
        title_prefix=f"🗞️ **Weekly Flight Digest for {origin} → {reg_disp}**"
    )

    if sent_msg:
        try:
            await sent_msg.edit_text(
                text=msg_text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            return
        except Exception:
            pass

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=msg_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to send digest report to user {user_id}: {e}")

db_manager = DatabaseManager(DB_PATH)

async def run_daily_cleanup_job(context):
    """Daily midnight UTC cleanup job for stale, expired, and paused trackers."""
    try:
        stats = await db_manager.purge_stale_trackers()
        logger.info(f"Daily cleanup job completed. Expired: {stats.get('expired', 0)}, Purged: {stats.get('purged', 0)}")
    except Exception as e:
        logger.error(f"Error during daily cleanup job: {e}")



