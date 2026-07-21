from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from providers.fast_flights import FastFlightsProvider
from services.resolver import LocationResolver
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager

SEARCH_ORIGIN, SEARCH_DESTINATION, SEARCH_DATE = range(10, 13)
resolver = LocationResolver()
provider = FastFlightsProvider()
db_manager = DatabaseManager(DB_PATH)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /search command."""
    args = context.args
    if args and len(args) >= 3:
        origin, destination, date = args[0].upper(), args[1].upper(), args[2]
        await execute_search(update, origin, destination, date)
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "🔍 **Instant Flight Search**\n\n"
        "🛫 **Step 1/3**: Where are you flying from? (e.g., 'Athens', 'ATH')",
        parse_mode="Markdown"
    )
    return SEARCH_ORIGIN

async def handle_search_origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another city or airport name.")
        return SEARCH_ORIGIN

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"src_org_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_src_org")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return SEARCH_ORIGIN

async def select_search_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_src_org":
        await query.message.edit_text("🛫 Enter origin city or airport code again:")
        return SEARCH_ORIGIN

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["search_origin_code"] = iata

    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🛬 **Step 2/3**: Where are you flying to? (e.g., 'London', 'LON')",
        parse_mode="Markdown"
    )
    return SEARCH_DESTINATION

async def handle_search_destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another destination.")
        return SEARCH_DESTINATION

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"src_dst_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_src_dst")])

    await update.message.reply_text("Please confirm your destination airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return SEARCH_DESTINATION

async def select_search_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_src_dst":
        await query.message.edit_text("🛬 Enter destination city or airport code again:")
        return SEARCH_DESTINATION

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["search_destination_code"] = iata

    await query.message.edit_text(
        f"✅ Destination set to: **{iata} - {name}**\n\n"
        "📅 **Step 3/3**: Enter departure date (`YYYY-MM-DD`):",
        parse_mode="Markdown"
    )
    return SEARCH_DATE

async def handle_search_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    origin = context.user_data["search_origin_code"]
    destination = context.user_data["search_destination_code"]

    await execute_search(update, origin, destination, date_str)
    return ConversationHandler.END

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

async def search_track_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for 'Track Prices for this Flight' button on search results."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) >= 5:
        origin, destination, date, price = parts[1], parts[2], parts[3], float(parts[4])
        user_id = query.from_user.id

        active_count = await db_manager.get_active_trackers_count(user_id)
        if active_count >= MAX_TRACKERS_PER_USER:
            await query.message.reply_text(
                f"⚠️ You have reached your limit of {MAX_TRACKERS_PER_USER} active trackers.\n"
                "Please delete an existing tracker using `/mytracks` first."
            )
            return

        tracker_id = await db_manager.create_tracker(
            user_id=user_id,
            origin_code=origin,
            origin_name=origin,
            destination_code=destination,
            destination_name=destination,
            departure_date=date,
            max_budget=price,
            frequency_hours=6
        )

        await query.message.reply_text(
            f"🔔 **Tracking Started!**\n\n"
            f"📍 **Route**: {origin} ✈️ {destination}\n"
            f"📅 **Date**: {date}\n"
            f"🎯 **Target Budget**: €{price:.2f}\n"
            f"🔄 **Polling Frequency**: Every 6 hours\n\n"
            "Fare Bot will notify you if prices drop lower!",
            parse_mode="Markdown"
        )
