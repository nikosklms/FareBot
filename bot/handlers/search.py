from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from providers.fast_flights import FastFlightsProvider
from services.resolver import LocationResolver

resolver = LocationResolver()
provider = FastFlightsProvider()

async def execute_search(
    update: Update, origin: str, destination: str, date: str
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    status_msg = await message.reply_text(f"🔍 Searching flights from **{origin}** to **{destination}** on **{date}**...", parse_mode="Markdown")

    offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date)

    if not offers:
        await status_msg.edit_text("❌ No flight offers found for the specified route and date.")
        return

    lowest = min(offers, key=lambda x: x.price)

    reply_text = (
        f"✈️ **Flight Search Results**\n\n"
        f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}\n"
        f"📅 **Date**: {lowest.departure_date}\n"
        f"💶 **Lowest Price**: {lowest.currency} {lowest.price:.2f}\n"
        f"🏢 **Airline**: {lowest.airline or 'Various'}\n"
    )

    keyboard = []
    if lowest.booking_url:
        keyboard.append([InlineKeyboardButton("🔗 View on Google Flights", url=lowest.booking_url)])
    keyboard.append([InlineKeyboardButton("🔔 Track Prices for this Flight", callback_data=f"track_{origin}_{destination}_{date}_{lowest.price}")])

    await status_msg.edit_text(reply_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
