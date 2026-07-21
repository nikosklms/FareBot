import logging
from datetime import datetime, timezone
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from database.db import DatabaseManager
from providers.base import AbstractFlightProvider
from config import MAX_CONSECUTIVE_FAILURES

logger = logging.getLogger(__name__)

class TrackerDaemonScheduler:
    def __init__(self, db: DatabaseManager, provider: AbstractFlightProvider):
        self.db = db
        self.provider = provider

    async def poll_tracker(self, tracker_id: int, bot: Bot):
        tracker = await self.db.get_tracker_by_id(tracker_id)
        if not tracker or tracker["status"] != "ACTIVE":
            return

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if tracker["departure_date"] < today_str:
            await self.db.update_tracker_status(tracker_id, "EXPIRED")
            await bot.send_message(
                chat_id=tracker["user_id"],
                text=f"ℹ️ Your tracker for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** on **{tracker['departure_date']}** has expired as the departure date has passed.",
                parse_mode="Markdown"
            )
            return

        offers = await self.provider.search_flights(
            origin=tracker["origin_code"],
            destination=tracker["destination_code"],
            departure_date=tracker["departure_date"]
        )

        if not offers:
            fails = await self.db.increment_failure_count(tracker_id)
            if fails >= MAX_CONSECUTIVE_FAILURES:
                await self.db.update_tracker_status(tracker_id, "PAUSED")
                await bot.send_message(
                    chat_id=tracker["user_id"],
                    text=f"⚠️ Unable to check prices for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** after 3 attempts. Tracker paused.",
                    parse_mode="Markdown"
                )
            return

        await self.db.reset_failure_count(tracker_id)
        lowest = min(offers, key=lambda x: x.price)
        await self.db.log_price(tracker_id, lowest.price, lowest.airline)

        if lowest.price <= tracker["max_budget"]:
            await self.db.update_tracker_status(tracker_id, "PAUSED")
            alert_text = (
                "🚨 **PRICE DROP ALERT!** 🚨\n\n"
                f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}\n"
                f"📅 **Date**: {lowest.departure_date}\n"
                f"🎯 **Target Budget**: €{tracker['max_budget']:.2f}\n"
                f"💶 **Current Price**: **€{lowest.price:.2f}**\n"
                f"🏢 **Airline**: {lowest.airline or 'Various'}"
            )
            buttons = [
                [InlineKeyboardButton("🔗 View & Book Flight", url=lowest.booking_url or "https://www.google.com/travel/flights")],
                [InlineKeyboardButton("⏸ Keep Paused", callback_data=f"dash_pause_{tracker_id}"), InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{tracker_id}")]
            ]
            await bot.send_message(
                chat_id=tracker["user_id"],
                text=alert_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
