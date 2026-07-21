from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from providers.fast_flights import FastFlightsProvider
from services.resolver import LocationResolver
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from daemon import schedule_tracker_job

SEARCH_ORIGIN, SEARCH_DESTINATION, SEARCH_DATE, SEARCH_FLIGHT_TYPE = range(10, 14)
resolver = LocationResolver()
provider = FastFlightsProvider()
db_manager = DatabaseManager(DB_PATH)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /search command."""
    args = context.args
    if args and len(args) >= 3:
        origin, destination, date_str = args[0].upper(), args[1].upper(), args[2]
        direct_only = False
        if len(args) >= 4 and args[3].lower() in ["direct", "direct_only", "--direct", "-d"]:
            direct_only = True

        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = datetime.now(timezone.utc).date()
            if parsed_date < today:
                await update.message.reply_text("❌ Departure date cannot be in the past.")
                return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("❌ Invalid date format. Use `YYYY-MM-DD` (e.g. `/search ATH LON 2026-08-15`).", parse_mode="Markdown")
            return ConversationHandler.END

        await execute_search(update, origin, destination, date_str, direct_only=direct_only)
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "🔍 **Instant Flight Search**\n\n"
        "🛫 **Step 1/4**: Where are you flying from? (e.g., 'Athens', 'ATH')",
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
        "🛬 **Step 2/4**: Where are you flying to? (e.g., 'London', 'LON')",
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
        "📅 **Step 3/4**: Enter departure date (`YYYY-MM-DD`):",
        parse_mode="Markdown"
    )
    return SEARCH_DATE

async def handle_search_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        if parsed_date < today:
            await update.message.reply_text("❌ Departure date cannot be in the past. Please enter a valid future date (`YYYY-MM-DD`):", parse_mode="Markdown")
            return SEARCH_DATE
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please enter date as `YYYY-MM-DD` (e.g. `2026-08-15`):", parse_mode="Markdown")
        return SEARCH_DATE

    context.user_data["search_departure_date"] = date_str

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="src_fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="src_fl_type_0")]
    ]
    await update.message.reply_text(
        "✈️ **Step 4/4**: Select your flight type preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return SEARCH_FLIGHT_TYPE

async def select_search_flight_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    direct_only = bool(int(query.data.split("_")[3]))

    origin = context.user_data["search_origin_code"]
    destination = context.user_data["search_destination_code"]
    date = context.user_data["search_departure_date"]

    await execute_search(update, origin, destination, date, direct_only=direct_only)
    return ConversationHandler.END


async def execute_search(
    update: Update, origin: str, destination: str, date: str, direct_only: bool = False
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    filter_label = "Direct Flights Only ✈️" if direct_only else "Any Flights 🔄"
    status_msg = await message.reply_text(f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** on **{date}**...", parse_mode="Markdown")

    offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date, direct_only=direct_only)

    if not offers:
        await status_msg.edit_text(f"❌ No matching flight offers found for **{origin} ✈️ {destination}** on **{date}** ({filter_label}).", parse_mode="Markdown")
        return

    top_offers = offers[:5]
    reply_lines = [
        f"✈️ **Top {len(top_offers)} Flight Results** ({filter_label})\n",
        f"📍 **Route**: {origin} ✈️ {destination} | 📅 **Date**: {date}\n"
    ]

    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    for i, o in enumerate(top_offers):
        stop_badge = "Direct ✈️" if o.is_direct else "1+ Stops 🔄"
        offset_str = f" (+{o.day_offset})" if getattr(o, "day_offset", 0) > 0 else ""
        time_info = f" | 🕒 {o.departure_time} ➔ {o.arrival_time}{offset_str}" if (o.departure_time and o.arrival_time) else ""
        reply_lines.append(f"{emojis[i]} **€{o.price:.2f}** — {o.airline or 'Various'} ({stop_badge}){time_info}")

    reply_text = "\n".join(reply_lines)


    lowest = top_offers[0]

    keyboard = []
    if lowest.booking_url:
        keyboard.append([InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=lowest.booking_url)])
    
    direct_flag_val = 1 if direct_only else 0
    keyboard.append([
        InlineKeyboardButton(f"🔔 Track Lowest (€{lowest.price:.2f})", callback_data=f"track_{origin}_{destination}_{date}_{lowest.price}_{direct_flag_val}")
    ])

    await status_msg.edit_text(reply_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def search_track_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for 'Track Prices for this Flight' button on search results."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) >= 5:
        origin, destination, date, price = parts[1], parts[2], parts[3], float(parts[4])
        direct_only = int(parts[5]) if len(parts) >= 6 else 0
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
            frequency_hours=6,
            direct_only=direct_only
        )

        if context.job_queue:
            schedule_tracker_job(context.job_queue, tracker_id, 6)

        flight_type_str = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
        await query.message.reply_text(
            f"🔔 **Tracking Started!**\n\n"
            f"📍 **Route**: {origin} ✈️ {destination}\n"
            f"📅 **Date**: {date}\n"
            f"✈️ **Flight Type**: {flight_type_str}\n"
            f"🎯 **Target Budget**: €{price:.2f}\n"
            f"🔄 **Polling Frequency**: Every 6 hours\n\n"
            "Fare Bot will notify you if prices drop lower!",
            parse_mode="Markdown"
        )


