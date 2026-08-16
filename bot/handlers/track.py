from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.resolver import LocationResolver
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from daemon import schedule_tracker_job
from bot.handlers.auth import restricted
from bot.inline_calendar import create_calendar
from utils.date_parser import parse_date_or_range, get_preset_range

ORIGIN, DESTINATION, DEPARTURE_DATE, FLIGHT_TYPE, BUDGET, FREQUENCY = range(6)
resolver = LocationResolver()
db_manager = DatabaseManager(DB_PATH)

@restricted
async def start_newtrack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    active_count = await db_manager.get_active_trackers_count(user_id)
    if active_count >= MAX_TRACKERS_PER_USER:
        await update.message.reply_text(
            f"⚠️ You have reached your limit of {MAX_TRACKERS_PER_USER} active trackers.\n"
            "Please delete an existing tracker using `/mytracks` before creating a new one."
        )
        return ConversationHandler.END

    args = context.args
    if args and len(args) >= 4:
        origin_raw, dest_raw, raw_date, budget_str = args[0], args[1], args[2], args[3]
        direct_only = 0
        if len(args) >= 5 and args[4].lower() in ["direct", "direct_only", "--direct", "-d"]:
            direct_only = 1

        origin_matches = resolver.resolve(origin_raw)
        dest_matches = resolver.resolve(dest_raw)

        if not origin_matches:
            await update.message.reply_text(f"❌ Origin location '{origin_raw}' not recognized.")
            return ConversationHandler.END
        if not dest_matches:
            await update.message.reply_text(f"❌ Destination location '{dest_raw}' not recognized.")
            return ConversationHandler.END

        origin, origin_name = origin_matches[0][0], origin_matches[0][1]
        destination, dest_name = dest_matches[0][0], dest_matches[0][1]

        try:
            budget = float(budget_str)
            if budget <= 0:
                await update.message.reply_text("❌ Budget must be a positive number greater than 0.")
                return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("❌ Invalid budget amount. Usage: `/track ATH LON 2026-09-01..2026-09-15 150`", parse_mode="Markdown")
            return ConversationHandler.END

        try:
            start_date, end_date = parse_date_or_range(raw_date)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if start_date < today_str:
                await update.message.reply_text("❌ Departure date cannot be in the past.")
                return ConversationHandler.END
        except Exception:
            await update.message.reply_text("❌ Invalid date format. Usage: `/track ATH LON 2026-09-01..2026-09-15 150`", parse_mode="Markdown")
            return ConversationHandler.END

        tracker_id = await db_manager.create_tracker(
            user_id=user_id,
            origin_code=origin,
            origin_name=origin_name,
            destination_code=destination,
            destination_name=dest_name,
            departure_date=start_date,
            departure_date_end=end_date,
            max_budget=budget,
            frequency_hours=6,
            direct_only=direct_only
        )

        if context.job_queue:
            schedule_tracker_job(context.job_queue, tracker_id, 6)

        flight_type_str = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
        date_display = f"{start_date} ➔ {end_date}" if end_date else start_date
        summary = (
            "✅ **Tracking Daemon Initialized!**\n\n"
            f"📍 **Route**: {origin} ({origin_name}) ✈️ {destination} ({dest_name})\n"
            f"📅 **Date**: {date_display}\n"
            f"✈️ **Flight Type**: {flight_type_str}\n"
            f"🎯 **Target Budget**: €{budget:.2f}\n"
            f"🔄 **Polling Frequency**: Every 6 hours\n\n"
            "You will receive a push notification as soon as a price drops below your budget!"
        )
        await update.message.reply_text(summary, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data.clear()
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
    await update.message.reply_text("🛫 **Step 1/6**: Where are you flying from? (e.g., 'Athens', 'ATH')", reply_markup=cancel_keyboard, parse_mode="Markdown")
    return ORIGIN

@restricted
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
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return ORIGIN

@restricted
async def select_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_org":
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
        await query.message.edit_text("🛫 Enter origin city or airport code again:", reply_markup=cancel_keyboard)
        return ORIGIN

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["origin_code"] = iata
    context.user_data["origin_name"] = name

    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🛬 **Step 2/6**: Where are you flying to? (e.g., 'London', 'LON')",
        reply_markup=cancel_keyboard,
        parse_mode="Markdown"
    )
    return DESTINATION

@restricted
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
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your destination airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return DESTINATION

@restricted
async def select_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_dst":
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
        await query.message.edit_text("🛬 Enter destination city or airport code again:", reply_markup=cancel_keyboard)
        return DESTINATION

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["destination_code"] = iata
    context.user_data["destination_name"] = name

    date_buttons = [
        [InlineKeyboardButton("🗓️ Next 7 Days", callback_data="datepreset_next_7_days"),
         InlineKeyboardButton("✈️ Next 14 Days", callback_data="datepreset_next_14_days")],
        [InlineKeyboardButton("📅 This Weekend", callback_data="datepreset_this_weekend"),
         InlineKeyboardButton("📆 Custom Calendar", callback_data="open_cal_track")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"✅ Destination set to: **{iata} - {name}**\n\n"
        "📅 **Step 3/6**: Select a quick date preset, open the calendar, or type a date / date range (`YYYY-MM-DD` or `YYYY-MM-DD..YYYY-MM-DD`):",
        reply_markup=InlineKeyboardMarkup(date_buttons),
        parse_mode="Markdown"
    )
    return DEPARTURE_DATE

@restricted
async def open_calendar_track_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cal_mode"] = "range"
    context.user_data.pop("cal_start_date", None)
    now = datetime.now(timezone.utc)
    calendar_markup = create_calendar(now.year, now.month, mode="range")
    await query.message.edit_text(
        "📆 **Interactive Date Picker**\nSelect departure date on calendar below:",
        reply_markup=calendar_markup,
        parse_mode="Markdown"
    )
    return DEPARTURE_DATE

@restricted
async def calendar_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target = query.data.replace("cal_nav_", "")
    year, month = map(int, target.split("-"))
    mode = context.user_data.get("cal_mode", "single")
    start_date = context.user_data.get("cal_start_date")
    calendar_markup = create_calendar(year, month, mode=mode, start_date=start_date)
    await query.message.edit_reply_markup(reply_markup=calendar_markup)
    return DEPARTURE_DATE

@restricted
async def track_calendar_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_mode = query.data.replace("cal_mode_", "")
    context.user_data["cal_mode"] = target_mode
    if target_mode == "single":
        context.user_data.pop("cal_start_date", None)

    year, month = datetime.now(timezone.utc).year, datetime.now(timezone.utc).month
    if query.message and query.message.reply_markup:
        for row in query.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("cal_nav_"):
                    try:
                        prev_year, prev_month = map(int, btn.callback_data.replace("cal_nav_", "").split("-"))
                        if prev_month == 12:
                            year, month = prev_year + 1, 1
                        else:
                            year, month = prev_year, prev_month + 1
                        break
                    except ValueError:
                        pass
            if "cal_nav_" in str(query.message.reply_markup):
                break
    start_date = context.user_data.get("cal_start_date")
    calendar_markup = create_calendar(year, month, mode=target_mode, start_date=start_date)
    await query.message.edit_reply_markup(reply_markup=calendar_markup)
    return DEPARTURE_DATE

@restricted
async def track_calendar_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return DEPARTURE_DATE


@restricted
async def handle_date_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    preset_key = query.data.replace("datepreset_", "")
    start_date, end_date = get_preset_range(preset_key)
    context.user_data["departure_date"] = start_date
    context.user_data["departure_date_end"] = end_date

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"📅 **Date Range**: {start_date} ➔ {end_date}\n\n"
        "✈️ **Step 4/6**: Select your flight type preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FLIGHT_TYPE

@restricted
async def handle_departure_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    try:
        start_date, end_date = parse_date_or_range(date_str)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if start_date < today_str:
            await update.message.reply_text("❌ Departure date cannot be in the past. Please enter a valid future date (`YYYY-MM-DD`):", parse_mode="Markdown")
            return DEPARTURE_DATE
    except Exception:
        await update.message.reply_text("❌ Invalid date format. Please enter date as `YYYY-MM-DD` or range as `YYYY-MM-DD..YYYY-MM-DD`:", parse_mode="Markdown")
        return DEPARTURE_DATE

    context.user_data["departure_date"] = start_date
    if end_date:
        context.user_data["departure_date_end"] = end_date
    else:
        context.user_data.pop("departure_date_end", None)

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    date_display = f"{start_date} ➔ {end_date}" if end_date else start_date
    await update.message.reply_text(
        f"📅 **Date**: {date_display}\n\n"
        "✈️ **Step 4/6**: Select your flight type preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FLIGHT_TYPE

@restricted
async def select_flight_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    direct_only = int(query.data.split("_")[2])
    context.user_data["direct_only"] = direct_only

    type_label = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
    await query.message.edit_text(
        f"✅ Flight type set to: **{type_label}**\n\n"
        "💶 **Step 5/6**: What is your maximum budget threshold in EUR? (e.g., `250`)",
        reply_markup=cancel_keyboard,
        parse_mode="Markdown"
    )
    return BUDGET

@restricted
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
        [InlineKeyboardButton("24 Hours (Daily)", callback_data="freq_24")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await update.message.reply_text(
        "⏰ **Step 6/6**: How often should Fare Bot check prices?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FREQUENCY

@restricted
async def select_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    freq_hours = int(query.data.split("_")[1])

    user_id = query.from_user.id
    ud = context.user_data
    direct_only = ud.get("direct_only", 0)
    dep_end = ud.get("departure_date_end")

    tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=ud["origin_code"],
        origin_name=ud["origin_name"],
        destination_code=ud["destination_code"],
        destination_name=ud["destination_name"],
        departure_date=ud["departure_date"],
        departure_date_end=dep_end,
        max_budget=ud["max_budget"],
        frequency_hours=freq_hours,
        direct_only=direct_only
    )

    if context.job_queue:
        schedule_tracker_job(context.job_queue, tracker_id, freq_hours)

    flight_type_str = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
    date_display = f"{ud['departure_date']} ➔ {dep_end}" if dep_end else ud["departure_date"]
    summary = (
        "✅ **Tracking Daemon Initialized!**\n\n"
        f"📍 **Route**: {ud['origin_code']} ✈️ {ud['destination_code']}\n"
        f"📅 **Date**: {date_display}\n"
        f"✈️ **Flight Type**: {flight_type_str}\n"
        f"🎯 **Target Budget**: €{ud['max_budget']:.2f}\n"
        f"🔄 **Polling Frequency**: Every {freq_hours} hours\n\n"
        "You will receive a push notification as soon as a price drops below your budget!"
    )
    await query.message.edit_text(summary, parse_mode="Markdown")
    return ConversationHandler.END

@restricted
async def handle_calendar_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    clicked_date = query.data.replace("cal_day_", "")
    mode = context.user_data.get("cal_mode", "single")

    if mode == "range":
        start_date = context.user_data.get("cal_start_date")
        if not start_date:
            # 1st click: Set start date
            context.user_data["cal_start_date"] = clicked_date
            dt = datetime.strptime(clicked_date, "%Y-%m-%d")
            calendar_markup = create_calendar(dt.year, dt.month, mode="range", start_date=clicked_date)
            await query.message.edit_text(
                f"📆 **Interactive Date Picker (Range Mode)**\nSelect **END** departure date (Start: `{clicked_date}`):",
                reply_markup=calendar_markup,
                parse_mode="Markdown"
            )
            return DEPARTURE_DATE
        else:
            # 2nd click: End date selected
            context.user_data.pop("cal_start_date", None)
            if start_date == clicked_date:
                dep_date = start_date
                dep_end = None
            else:
                dep_date = start_date
                dep_end = clicked_date
    else:
        dep_date = clicked_date
        dep_end = None

    user_id = update.effective_user.id
    origin = context.user_data.get("track_origin") or context.user_data.get("origin_code")
    destination = context.user_data.get("track_destination") or context.user_data.get("destination_code")

    if await db_manager.has_active_tracker(user_id, origin, destination, dep_date):
        buttons = [
            [InlineKeyboardButton("✏️ Update Existing Budget", callback_data="dash_editbudget_1")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
        ]
        await query.message.reply_text(
            f"⚠️ **Duplicate Tracker Detected!**\n\n"
            f"You are already tracking **{origin} → {destination}** for **{dep_date}**.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )
        return DEPARTURE_DATE

    context.user_data["departure_date"] = dep_date
    context.user_data["departure_date_end"] = dep_end

    date_display = f"{dep_date} ➔ {dep_end}" if dep_end else dep_date
    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"📅 **Date**: {date_display}\n\n"
        "✈️ **Step 4/6**: Select your flight type preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FLIGHT_TYPE


