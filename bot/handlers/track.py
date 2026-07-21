from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.resolver import LocationResolver
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from daemon import schedule_tracker_job

ORIGIN, DESTINATION, DEPARTURE_DATE, FLIGHT_TYPE, BUDGET, FREQUENCY = range(6)
resolver = LocationResolver()
db_manager = DatabaseManager(DB_PATH)

async def start_newtrack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    active_count = await db_manager.get_active_trackers_count(user_id)
    if active_count >= MAX_TRACKERS_PER_USER:
        await update.message.reply_text(
            f"⚠️ You have reached your limit of {MAX_TRACKERS_PER_USER} active trackers.\n"
            "Please delete an existing tracker using `/mytracks` before creating a new one."
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("🛫 **Step 1/6**: Where are you flying from? (e.g., 'Athens', 'ATH')", parse_mode="Markdown")
    return ORIGIN

async def handle_origin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another city or airport name.")
        return ORIGIN

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"sel_org_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_org")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return ORIGIN

async def select_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_org":
        await query.message.edit_text("🛫 Enter origin city or airport code again:")
        return ORIGIN

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["origin_code"] = iata
    context.user_data["origin_name"] = name

    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🛬 **Step 2/6**: Where are you flying to? (e.g., 'London', 'LON')",
        parse_mode="Markdown"
    )
    return DESTINATION

async def handle_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another destination.")
        return DESTINATION

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"sel_dst_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_dst")])

    await update.message.reply_text("Please confirm your destination airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return DESTINATION

async def select_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_dst":
        await query.message.edit_text("🛬 Enter destination city or airport code again:")
        return DESTINATION

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["destination_code"] = iata
    context.user_data["destination_name"] = name

    await query.message.edit_text(
        f"✅ Destination set to: **{iata} - {name}**\n\n"
        "📅 **Step 3/6**: Enter departure date (`YYYY-MM-DD`):",
        parse_mode="Markdown"
    )
    return DEPARTURE_DATE

async def handle_departure_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        if parsed_date < today:
            await update.message.reply_text("❌ Departure date cannot be in the past. Please enter a valid future date (`YYYY-MM-DD`):", parse_mode="Markdown")
            return DEPARTURE_DATE
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please enter date as `YYYY-MM-DD` (e.g. `2026-08-15`):", parse_mode="Markdown")
        return DEPARTURE_DATE

    context.user_data["departure_date"] = date_str

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="fl_type_0")]
    ]
    await update.message.reply_text(
        "✈️ **Step 4/6**: Select your flight type preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FLIGHT_TYPE

async def select_flight_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    direct_only = int(query.data.split("_")[2])
    context.user_data["direct_only"] = direct_only

    type_label = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
    await query.message.edit_text(
        f"✅ Flight type set to: **{type_label}**\n\n"
        "💶 **Step 5/6**: What is your maximum budget threshold in EUR? (e.g., `250`)",
        parse_mode="Markdown"
    )
    return BUDGET

async def handle_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        budget = float(update.message.text.strip())
        if budget <= 0:
            await update.message.reply_text("❌ Budget must be a positive number greater than 0. Please enter a valid amount:")
            return BUDGET
        context.user_data["max_budget"] = budget
    except ValueError:
        await update.message.reply_text("❌ Invalid budget amount. Please enter a number (e.g. `250`).")
        return BUDGET

    buttons = [
        [InlineKeyboardButton("6 Hours (Min)", callback_data="freq_6")],
        [InlineKeyboardButton("12 Hours", callback_data="freq_12")],
        [InlineKeyboardButton("24 Hours (Daily)", callback_data="freq_24")]
    ]
    await update.message.reply_text(
        "⏰ **Step 6/6**: How often should Fare Bot check prices?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FREQUENCY

async def select_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    freq_hours = int(query.data.split("_")[1])

    user_id = query.from_user.id
    ud = context.user_data
    direct_only = ud.get("direct_only", 0)

    tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=ud["origin_code"],
        origin_name=ud["origin_name"],
        destination_code=ud["destination_code"],
        destination_name=ud["destination_name"],
        departure_date=ud["departure_date"],
        max_budget=ud["max_budget"],
        frequency_hours=freq_hours,
        direct_only=direct_only
    )

    if context.job_queue:
        schedule_tracker_job(context.job_queue, tracker_id, freq_hours)

    flight_type_str = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
    summary = (
        "✅ **Tracking Daemon Initialized!**\n\n"
        f"📍 **Route**: {ud['origin_code']} ✈️ {ud['destination_code']}\n"
        f"📅 **Date**: {ud['departure_date']}\n"
        f"✈️ **Flight Type**: {flight_type_str}\n"
        f"🎯 **Target Budget**: €{ud['max_budget']:.2f}\n"
        f"🔄 **Polling Frequency**: Every {freq_hours} hours\n\n"
        "You will receive a push notification as soon as a price drops below your budget!"
    )
    await query.message.edit_text(summary, parse_mode="Markdown")
    return ConversationHandler.END


