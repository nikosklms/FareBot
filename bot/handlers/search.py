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
from bot.handlers.auth import restricted
from bot.inline_calendar import create_calendar

from utils.date_parser import parse_date_or_range, get_preset_range

SEARCH_ORIGIN, SEARCH_DESTINATION, SEARCH_DATE, SEARCH_FLIGHT_TYPE = range(10, 14)
resolver = LocationResolver()
provider = FastFlightsProvider()
db_manager = DatabaseManager(DB_PATH)

@restricted
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /search command."""
    args = context.args
    if args and len(args) >= 3:
        origin_raw, dest_raw, raw_date = args[0], args[1], args[2]
        direct_only = False
        if len(args) >= 4 and args[3].lower() in ["direct", "direct_only", "--direct", "-d"]:
            direct_only = True

        origin_matches = resolver.resolve(origin_raw)
        dest_matches = resolver.resolve(dest_raw)

        if not origin_matches:
            await update.message.reply_text(f"❌ Origin location '{origin_raw}' not recognized.")
            return ConversationHandler.END
        if not dest_matches:
            await update.message.reply_text(f"❌ Destination location '{dest_raw}' not recognized.")
            return ConversationHandler.END

        origin = origin_matches[0][0]
        destination = dest_matches[0][0]

        try:
            start_date, end_date = parse_date_or_range(raw_date)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if start_date < today_str:
                await update.message.reply_text("❌ Departure date cannot be in the past.")
                return ConversationHandler.END
        except Exception:
            await update.message.reply_text("❌ Invalid date or range format. Use `YYYY-MM-DD` or `YYYY-MM-DD..YYYY-MM-DD`.", parse_mode="Markdown")
            return ConversationHandler.END

        await execute_search(update, origin, destination, raw_date, direct_only=direct_only)
        return ConversationHandler.END

    context.user_data.clear()
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
    await update.message.reply_text(
        "🔍 **Instant Flight Search**\n\n"
        "🛫 **Step 1/4**: Where are you flying from? (e.g., 'Athens', 'ATH')",
        reply_markup=cancel_keyboard,
        parse_mode="Markdown"
    )
    return SEARCH_ORIGIN

@restricted
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
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return SEARCH_ORIGIN

@restricted
async def select_search_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_src_org":
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
        await query.message.edit_text("🛫 Enter origin city or airport code again:", reply_markup=cancel_keyboard)
        return SEARCH_ORIGIN

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["search_origin_code"] = iata

    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
    await query.message.edit_text(f"🛫 **Origin**: {iata} - {name}\n\n🛬 **Step 2/4**: Where are you flying to? (e.g., 'London', 'LON')", reply_markup=cancel_keyboard, parse_mode="Markdown")
    return SEARCH_DESTINATION

@restricted
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
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your destination airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return SEARCH_DESTINATION

@restricted
async def select_search_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_src_dst":
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])
        await query.message.edit_text("🛬 Enter destination city or airport code again:", reply_markup=cancel_keyboard)
        return SEARCH_DESTINATION

    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["search_destination_code"] = iata

    date_buttons = [
        [InlineKeyboardButton("🗓️ Next 7 Days", callback_data="src_datepreset_next_7_days"),
         InlineKeyboardButton("✈️ Next 14 Days", callback_data="src_datepreset_next_14_days")],
        [InlineKeyboardButton("📅 This Weekend", callback_data="src_datepreset_this_weekend"),
         InlineKeyboardButton("📆 Custom Calendar", callback_data="open_cal_search")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"🛬 **Destination**: {iata} - {name}\n\n"
        "📅 **Step 3/4**: Select a quick date preset, open the calendar, or type a date / date range (`YYYY-MM-DD` or `YYYY-MM-DD..YYYY-MM-DD`):",
        reply_markup=InlineKeyboardMarkup(date_buttons),
        parse_mode="Markdown"
    )
    return SEARCH_DATE

@restricted
async def open_calendar_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return SEARCH_DATE

@restricted
async def search_calendar_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target = query.data.replace("cal_nav_", "")
    year, month = map(int, target.split("-"))
    mode = context.user_data.get("cal_mode", "single")
    start_date = context.user_data.get("cal_start_date")
    calendar_markup = create_calendar(year, month, mode=mode, start_date=start_date)
    await query.message.edit_reply_markup(reply_markup=calendar_markup)
    return SEARCH_DATE

@restricted
async def search_calendar_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return SEARCH_DATE

@restricted
async def search_calendar_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return SEARCH_DATE


@restricted
async def handle_search_calendar_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            return SEARCH_DATE
        else:
            # 2nd click: End date selected
            context.user_data.pop("cal_start_date", None)
            if start_date == clicked_date:
                dep_date = start_date
            else:
                dep_date = f"{start_date}..{clicked_date}"
    else:
        dep_date = clicked_date

    context.user_data["search_departure_date"] = dep_date

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="src_fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="src_fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"📅 **Departure Date**: {dep_date}\n\n"
        "⚙️ **Step 4/4**: What type of flights do you want?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return SEARCH_FLIGHT_TYPE

@restricted
async def handle_search_date_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    preset_key = query.data.replace("src_datepreset_", "")
    start_date, end_date = get_preset_range(preset_key)
    date_str = f"{start_date}..{end_date}" if end_date else start_date
    context.user_data["search_departure_date"] = date_str

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="src_fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="src_fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    await query.message.edit_text(
        f"📅 **Date Range**: {start_date} ➔ {end_date}\n\n"
        "⚙️ **Step 4/4**: What type of flights do you want?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return SEARCH_FLIGHT_TYPE

@restricted
async def handle_search_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    try:
        start_date, end_date = parse_date_or_range(date_str)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if start_date < today_str:
            await update.message.reply_text("❌ Departure date cannot be in the past. Please enter a valid future date (`YYYY-MM-DD`):", parse_mode="Markdown")
            return SEARCH_DATE
    except Exception:
        await update.message.reply_text("❌ Invalid date format. Please enter date as `YYYY-MM-DD` or range as `YYYY-MM-DD..YYYY-MM-DD`:", parse_mode="Markdown")
        return SEARCH_DATE

    context.user_data["search_departure_date"] = date_str

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="src_fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="src_fl_type_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]
    date_display = f"{start_date} ➔ {end_date}" if end_date else start_date
    await update.message.reply_text(f"📅 **Date**: {date_display}\n\n⚙️ **Step 4/4**: What type of flights do you want?", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    return SEARCH_FLIGHT_TYPE

@restricted
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
    start_date, end_date = parse_date_or_range(date)

    if end_date:
        status_msg = await message.reply_text(f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** between **{start_date}** and **{end_date}**...", parse_mode="Markdown")
        offers = await provider.search_flights_range(origin=origin, destination=destination, start_date=start_date, end_date=end_date, direct_only=direct_only)
    else:
        status_msg = await message.reply_text(f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** on **{date}**...", parse_mode="Markdown")
        offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date, direct_only=direct_only)

    if not offers:
        await status_msg.edit_text(f"❌ No matching flight offers found for **{origin} ✈️ {destination}** on **{date}** ({filter_label}).", parse_mode="Markdown")
        return

    top_offers = offers[:5]
    date_display = f"{start_date} ➔ {end_date}" if end_date else date
    reply_lines = [
        f"✈️ **Top {len(top_offers)} Flight Results** ({filter_label})\n",
        f"📍 **Route**: {origin} ✈️ {destination} | 📅 **Date**: {date_display}\n"
    ]

    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    for i, o in enumerate(top_offers):
        stop_badge = "Direct ✈️" if o.is_direct else "1+ Stops 🔄"
        offset_str = f" (+{o.day_offset})" if getattr(o, "day_offset", 0) > 0 else ""
        time_info = f" | 🕒 {o.departure_time} ➔ {o.arrival_time}{offset_str}" if (o.departure_time and o.arrival_time) else ""
        date_badge = f" ({o.departure_date})" if end_date else ""
        price_str = f"[**€{o.price:.2f}**]({o.booking_url})" if o.booking_url else f"**€{o.price:.2f}**"
        reply_lines.append(f"{emojis[i]} {price_str}{date_badge} — {o.airline or 'Various'} ({stop_badge}){time_info}")

    reply_text = "\n".join(reply_lines)

    lowest = top_offers[0]
    from providers.fast_flights import build_google_flights_url
    booking_url = lowest.booking_url or build_google_flights_url(origin, destination, lowest.departure_date, direct_only=direct_only)

    keyboard = [
        [InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=booking_url)]
    ]

    direct_flag_val = 1 if direct_only else 0
    cb_date = f"{start_date}:{end_date}" if end_date else start_date
    keyboard.append([
        InlineKeyboardButton(f"🔔 Track Lowest (€{lowest.price:.2f})", callback_data=f"track_{origin}_{destination}_{cb_date}_{lowest.price}_{direct_flag_val}")
    ])

    await status_msg.edit_text(reply_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

@restricted
async def search_track_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for 'Track Prices for this Flight' button on search results."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) >= 5:
        origin, destination, raw_date, price = parts[1], parts[2], parts[3], float(parts[4])
        direct_only = int(parts[5]) if len(parts) >= 6 else 0
        user_id = query.from_user.id

        if ":" in raw_date:
            dep_start, dep_end = raw_date.split(":", 1)
        else:
            dep_start, dep_end = raw_date, None

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
            departure_date=dep_start,
            departure_date_end=dep_end,
            max_budget=price,
            frequency_hours=6,
            direct_only=direct_only
        )

        if context.job_queue:
            schedule_tracker_job(context.job_queue, tracker_id, 6)

        flight_type_str = "Direct Flights Only ✈️" if direct_only else "Any Flights (Direct & Layovers) 🔄"
        date_display_str = f"{dep_start} ➔ {dep_end}" if dep_end else dep_start
        await query.message.reply_text(
            f"🔔 **Tracking Started!**\n\n"
            f"📍 **Route**: {origin} ✈️ {destination}\n"
            f"📅 **Date**: {date_display_str}\n"
            f"✈️ **Flight Type**: {flight_type_str}\n"
            f"🎯 **Target Budget**: €{price:.2f}\n"
            f"🔄 **Polling Frequency**: Every 6 hours\n\n"
            "Fare Bot will notify you if prices drop lower!",
            parse_mode="Markdown"
        )


