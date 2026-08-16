import logging
import time
from typing import Any, Dict, List, Optional
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
from services.explore_engine import calculate_discount_score

from utils.date_parser import parse_date_or_range, get_preset_range

logger = logging.getLogger(__name__)

SEARCH_ORIGIN, SEARCH_DESTINATION, SEARCH_DATE, SEARCH_FLIGHT_TYPE, SEARCH_SORT = range(10, 15)
resolver = LocationResolver()
provider = FastFlightsProvider()
db_manager = DatabaseManager(DB_PATH)

@restricted
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /search command."""
    user_id = update.effective_user.id if update.effective_user else "unknown"
    args = context.args
    logger.info(f"[SEARCH] User {user_id} invoked /search with args={args}")

    if args and len(args) >= 3:
        origin_raw, dest_raw, raw_date = args[0], args[1], args[2]
        direct_only = False
        if len(args) >= 4 and args[3].lower() in ["direct", "direct_only", "--direct", "-d"]:
            direct_only = True

        origin_matches = resolver.resolve(origin_raw)
        dest_matches = resolver.resolve(dest_raw)

        if not origin_matches:
            logger.warning(f"[SEARCH] User {user_id}: Origin location '{origin_raw}' not recognized.")
            await update.message.reply_text(f"❌ Origin location '{origin_raw}' not recognized.")
            return ConversationHandler.END
        if not dest_matches:
            logger.warning(f"[SEARCH] User {user_id}: Destination location '{dest_raw}' not recognized.")
            await update.message.reply_text(f"❌ Destination location '{dest_raw}' not recognized.")
            return ConversationHandler.END

        origin = origin_matches[0][0]
        destination = dest_matches[0][0]

        try:
            start_date, end_date = parse_date_or_range(raw_date)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if start_date < today_str:
                logger.warning(f"[SEARCH] User {user_id}: Departure date {start_date} is in the past.")
                await update.message.reply_text("❌ Departure date cannot be in the past.")
                return ConversationHandler.END
        except Exception as e:
            logger.warning(f"[SEARCH] User {user_id}: Invalid date format '{raw_date}': {e}")
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

def _format_search_offer(o: Any, idx_emoji: str, has_end_date: bool) -> str:
    stop_badge = "Direct ✈️" if getattr(o, "is_direct", True) else "1+ Stops 🔄"
    offset_val = getattr(o, "day_offset", 0)
    offset_str = f" (+{offset_val})" if offset_val > 0 else ""
    dep_time = getattr(o, "departure_time", None)
    arr_time = getattr(o, "arrival_time", None)
    time_info = f" | 🕒 {dep_time} ➔ {arr_time}{offset_str}" if (dep_time and arr_time) else ""
    date_badge = f" ({o.departure_date})" if has_end_date else ""
    booking_url = getattr(o, "booking_url", None)
    price_str = f"[€{o.price:.2f}]({booking_url})" if booking_url else f"€{o.price:.2f}"

    typ_min = getattr(o, "typical_min", None)
    typ_max = getattr(o, "typical_max", None)
    disc_pct = calculate_discount_score(o.price, typ_min, typ_max) if (typ_min or typ_max) else 0.0
    base_price = ((typ_min + typ_max) / 2.0) if (typ_min and typ_max) else None

    if base_price and disc_pct > 0:
        disc_badge = f" (💥 **{disc_pct:.0f}% OFF!** | Avg: ~€{base_price:.2f})"
    elif base_price and disc_pct < 0:
        disc_badge = f" (📈 **+{abs(disc_pct):.0f}% EXPENSIVE** | Avg: ~€{base_price:.2f})"
    elif base_price:
        disc_badge = f" (📊 Avg: ~€{base_price:.2f})"
    else:
        disc_badge = ""

    airline_name = getattr(o, "airline", None) or "Various"
    return f"{idx_emoji} **{price_str}**{disc_badge}{date_badge} — {airline_name} ({stop_badge}){time_info}"

async def execute_search(
    update: Update, origin: str, destination: str, date: str, direct_only: bool = False
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    t_start = time.perf_counter()
    user_id = update.effective_user.id if update.effective_user else "unknown"
    logger.info(f"[SEARCH] Executing search for user {user_id}: {origin} -> {destination} on {date} (direct_only={direct_only})")

    filter_label = "Direct Flights Only ✈️" if direct_only else "Any Flights 🔄"
    start_date, end_date = parse_date_or_range(date)

    from bot.handlers.common import build_status_estimate_text
    from utils.date_parser import generate_date_sequence
    import math

    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])

    if end_date:
        dates = generate_date_sequence(start_date, end_date)
        num_days = len(dates)
        est_sec = math.ceil(num_days / 3) * 1.25
        hdr = f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** between **{start_date}** and **{end_date}**..."
        status_text = build_status_estimate_text(hdr, est_sec, total_queries=num_days, num_airports=1, num_days=num_days)
        status_msg = await message.reply_text(status_text, parse_mode="Markdown", reply_markup=cancel_markup)
        offers = await provider.search_flights_range(origin=origin, destination=destination, start_date=start_date, end_date=end_date, direct_only=direct_only)
    else:
        hdr = f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** on **{date}**..."
        status_text = build_status_estimate_text(hdr, est_seconds=2.5, total_queries=1, num_airports=1, num_days=1)
        status_msg = await message.reply_text(status_text, parse_mode="Markdown", reply_markup=cancel_markup)
        offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date, direct_only=direct_only)

    elapsed_s = time.perf_counter() - t_start

    if not offers:
        logger.info(f"[SEARCH] Search completed for user {user_id} in {elapsed_s:.2f}s: 0 offers found.")
        await status_msg.edit_text(f"❌ No matching flight offers found for **{origin} ✈️ {destination}** on **{date}** ({filter_label}).", parse_mode="Markdown")
        return

    logger.info(f"[SEARCH] Search completed for user {user_id} in {elapsed_s:.2f}s: {len(offers)} offers found.")
    offers.sort(key=lambda x: x.price)
    top_offers = offers[:5]
    date_display = f"{start_date} ➔ {end_date}" if end_date else date
    reply_lines = [
        f"✈️ **Top {len(top_offers)} Flight Results** ({filter_label})\n",
        f"📍 **Route**: {origin} ✈️ {destination} | 📅 **Date**: {date_display}\n"
    ]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    for i, o in enumerate(top_offers):
        reply_lines.append(_format_search_offer(o, emojis[i], bool(end_date)))

    lowest = top_offers[0]
    reply_text = "\n".join(reply_lines)

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

    await status_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard))

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


