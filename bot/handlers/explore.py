import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from bot.handlers.auth import restricted
from bot.inline_calendar import create_calendar
from services.explore_engine import run_explore_query
from services.resolver import LocationResolver

logger = logging.getLogger(__name__)
db_manager = DatabaseManager(DB_PATH)
resolver = LocationResolver()

EXPLORE_ORIGIN, EXPLORE_REGION, EXPLORE_SORT, EXPLORE_TIMEFRAME, EXPLORE_BUDGET, EXPLORE_LIMIT = range(6)

@restricted
async def start_explore_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start interactive /explore wizard or execute one-line shortcut if args provided."""
    args = context.args or []

    # One-line shortcut execution
    if len(args) >= 2:
        origin = args[0].upper()
        region = args[1].lower()

        tf = 30
        max_budget = None
        limit = 10

        if len(args) > 2:
            if args[2].isdigit():
                tf = int(args[2])
            elif len(args) > 3 and args[3].isdigit():
                tf = int(args[2])
                max_budget = float(args[3])
            else:
                try:
                    max_budget = float(args[2])
                except ValueError:
                    pass

        if len(args) > 3 and max_budget is None and args[3].isdigit():
            max_budget = float(args[3])

        if len(args) > 4 and args[4].isdigit():
            limit = int(args[4])

        dep_date = (datetime.now(timezone.utc) + timedelta(days=tf)).strftime("%Y-%m-%d")
        status_msg = f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}** ({tf}d out)..."
        await update.message.reply_text(status_msg, parse_mode="Markdown")

        deals = await run_explore_query(origin, region, dep_date, max_budget=max_budget, max_results=limit)
        await _render_explore_deals(update.message, origin, region, deals)
        return ConversationHandler.END

    # Start multi-step wizard
    context.user_data.clear()
    buttons = [
        [InlineKeyboardButton("ATH - Athens", callback_data="expl_org_ATH_Athens"), InlineKeyboardButton("SKG - Thessaloniki", callback_data="expl_org_SKG_Thessaloniki")],
        [InlineKeyboardButton("HER - Heraklion", callback_data="expl_org_HER_Heraklion"), InlineKeyboardButton("LON - London", callback_data="expl_org_LON_London")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await update.message.reply_text(
        "🌟 **Explore Top Flight Deals Wizard**\n\n"
        "🛫 **Step 1/5**: Select origin airport:\n"
        "Select a quick origin airport below or type city/airport name (e.g., 'Athens', 'ATH'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXPLORE_ORIGIN

@restricted
async def handle_explore_origin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another city or airport name.")
        return EXPLORE_ORIGIN

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"expl_org_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return EXPLORE_ORIGIN

@restricted
async def select_explore_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 3)
    iata, name = parts[2], parts[3]
    context.user_data["explore_origin"] = iata

    buttons = [
        [InlineKeyboardButton("🇪🇺 Europe", callback_data="expl_reg_europe"), InlineKeyboardButton("🏝️ Greek Islands", callback_data="expl_reg_islands")],
        [InlineKeyboardButton("🕌 Middle East", callback_data="expl_reg_middle_east"), InlineKeyboardButton("⛩️ Asia", callback_data="expl_reg_asia")],
        [InlineKeyboardButton("🌍 Africa", callback_data="expl_reg_africa"), InlineKeyboardButton("🦘 Oceania", callback_data="expl_reg_oceania")],
        [InlineKeyboardButton("💃 Latin America", callback_data="expl_reg_latin_america"), InlineKeyboardButton("🗽 North America", callback_data="expl_reg_north_america")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🌍 **Step 2/5**: Select a destination region to explore:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXPLORE_REGION

@restricted
async def select_explore_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    region = query.data.split("_", 2)[2]
    context.user_data["explore_region"] = region

    buttons = [
        [InlineKeyboardButton("💶 Cheapest Price", callback_data="expl_sort_price"), InlineKeyboardButton("💥 Highest Discount %", callback_data="expl_sort_discount")],
        [InlineKeyboardButton("🔀 Show Both Lists", callback_data="expl_sort_both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Region set to: **{region.upper().replace('_', ' ')}**\n\n"
        "📊 **Step 3/6**: How would you like flight deals sorted?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXPLORE_SORT

@restricted
async def select_explore_sort_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    sort_mode = query.data.replace("expl_sort_", "")
    context.user_data["explore_sort"] = sort_mode

    buttons = [
        [InlineKeyboardButton("⚡ Next Weekend (7d)", callback_data="expl_tf_7"), InlineKeyboardButton("📅 14 Days", callback_data="expl_tf_14")],
        [InlineKeyboardButton("🗓️ 30 Days (Default)", callback_data="expl_tf_30"), InlineKeyboardButton("✈️ 60 Days", callback_data="expl_tf_60")],
        [InlineKeyboardButton("🌍 90 Days", callback_data="expl_tf_90"), InlineKeyboardButton("📆 Custom Calendar", callback_data="open_cal_explore")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    sort_labels = {
        "price": "Cheapest Price 💶",
        "discount": "Highest Discount % 💥",
        "both": "Show Both Lists 🔀"
    }
    label = sort_labels.get(sort_mode, sort_mode)

    await query.message.edit_text(
        f"✅ Sort mode set to: **{label}**\n\n"
        "📅 **Step 4/6**: Select departure timeframe horizon, open the custom calendar, or type days ahead (e.g. '45'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXPLORE_TIMEFRAME

@restricted
async def open_calendar_explore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return EXPLORE_TIMEFRAME

@restricted
async def explore_calendar_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target = query.data.replace("cal_nav_", "")
    year, month = map(int, target.split("-"))
    mode = context.user_data.get("cal_mode", "single")
    start_date = context.user_data.get("cal_start_date")
    calendar_markup = create_calendar(year, month, mode=mode, start_date=start_date)
    await query.message.edit_reply_markup(reply_markup=calendar_markup)
    return EXPLORE_TIMEFRAME

@restricted
async def explore_calendar_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    return EXPLORE_TIMEFRAME

@restricted
async def explore_calendar_ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return EXPLORE_TIMEFRAME

@restricted
async def handle_explore_calendar_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    clicked_date = query.data.replace("cal_day_", "")
    mode = context.user_data.get("cal_mode", "single")

    if mode == "range":
        start_date = context.user_data.get("cal_start_date")
        if not start_date:
            context.user_data["cal_start_date"] = clicked_date
            dt = datetime.strptime(clicked_date, "%Y-%m-%d")
            calendar_markup = create_calendar(dt.year, dt.month, mode="range", start_date=clicked_date)
            await query.message.edit_text(
                f"📆 **Interactive Date Picker (Range Mode)**\nSelect **END** departure date (Start: `{clicked_date}`):",
                reply_markup=calendar_markup,
                parse_mode="Markdown"
            )
            return EXPLORE_TIMEFRAME
        else:
            context.user_data.pop("cal_start_date", None)
            dep_date = start_date if start_date == clicked_date else f"{start_date}..{clicked_date}"
            target_start = start_date
    else:
        dep_date = clicked_date
        target_start = clicked_date

    context.user_data["explore_departure_date"] = dep_date
    today = datetime.now(timezone.utc).date()
    start_dt = datetime.strptime(target_start, "%Y-%m-%d").date()
    days_diff = max(1, (start_dt - today).days)
    context.user_data["explore_timeframe"] = days_diff

    return await _ask_explore_limit(query.message, context, is_callback=True)

@restricted
async def handle_explore_timeframe_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 330):
        await update.message.reply_text("❌ Please enter a number between 1 and 330 days ahead (e.g. '30') or tap a button below.")
        return EXPLORE_TIMEFRAME

    context.user_data["explore_timeframe"] = int(text)
    return await _ask_explore_limit(update.message, context)

@restricted
async def select_explore_timeframe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    days = int(query.data.split("_")[2])
    context.user_data["explore_timeframe"] = days
    return await _ask_explore_limit(query.message, context, is_callback=True)

async def _ask_explore_limit(message, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False) -> int:
    tf = context.user_data.get("explore_timeframe", 30)

    buttons = [
        [InlineKeyboardButton("5", callback_data="expl_lim_5"), InlineKeyboardButton("10 (Default)", callback_data="expl_lim_10")],
        [InlineKeyboardButton("15", callback_data="expl_lim_15"), InlineKeyboardButton("20", callback_data="expl_lim_20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    msg_text = (
        f"✅ Departure Timeframe set to: **{tf} Days Ahead**\n\n"
        "📊 **Step 5/5**: How many top flight deal results would you like to view? (1 to 20, default 10):"
    )

    if is_callback:
        await message.edit_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply_text(msg_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    return EXPLORE_LIMIT

@restricted
async def handle_explore_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 20):
        await update.message.reply_text("❌ Please enter a number between 1 and 20 (or tap a button below).")
        return EXPLORE_LIMIT

    limit = int(text)
    return await _execute_wizard_explore(update.message, context, limit)

@restricted
async def select_explore_limit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    limit = int(query.data.split("_")[2])
    return await _execute_wizard_explore(query.message, context, limit, is_callback=True)

async def _execute_wizard_explore(message, context: ContextTypes.DEFAULT_TYPE, limit: int, is_callback: bool = False) -> int:
    origin = context.user_data.get("explore_origin", "ATH")
    region = context.user_data.get("explore_region", "europe")
    sort_mode = context.user_data.get("explore_sort", "both")
    tf = context.user_data.get("explore_timeframe", 30)
    custom_dep_date = context.user_data.get("explore_departure_date")

    if custom_dep_date:
        dep_date = custom_dep_date
    else:
        dep_date = (datetime.now(timezone.utc) + timedelta(days=tf)).strftime("%Y-%m-%d")

    status_msg = f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}** ({dep_date})..."

    if is_callback:
        await message.edit_text(status_msg, parse_mode="Markdown")
    else:
        await message.reply_text(status_msg, parse_mode="Markdown")

    deals = await run_explore_query(origin, region, dep_date, sort_by=sort_mode, max_results=limit)
    await _render_explore_deals(message, origin, region, deals)
    context.user_data.clear()
    return ConversationHandler.END

def _format_deal_item(d: Dict[str, Any], idx: int, show_percentage: bool = True) -> tuple[str, InlineKeyboardButton]:
    from providers.fast_flights import build_google_flights_url

    disc_pct = d.get("discount_pct", 0.0)
    base_price = d.get("baseline_price")

    if show_percentage and base_price and disc_pct > 0:
        disc_text = f" (💥 **{disc_pct:.0f}% OFF!** | Avg: ~€{base_price:.2f})"
    elif show_percentage and base_price and disc_pct < 0:
        disc_text = f" (📈 **{disc_pct:.0f}% EXPENSIVE** | Avg: ~€{base_price:.2f})"
    elif base_price:
        disc_text = f" (Avg: ~€{base_price:.2f})"
    else:
        disc_text = ""

    flights_url = build_google_flights_url(d["origin_code"], d["destination_code"], d["departure_date"])
    price_str = f"[€{d['price']:.2f}]({flights_url})"

    line = (
        f"{idx}. **{d['origin_code']} ✈️ {d['destination_code']} ({d['destination_name']})**\n"
        f"💶 **{price_str}**{disc_text} | 📅 {d['departure_date']} ({d['airline']})\n"
    )
    cb_data = f"track_deal_{d['origin_code']}_{d['destination_code']}_{d['departure_date']}_{d['price']}"
    btn = InlineKeyboardButton(f"🔔 Track Deal #{idx} (€{d['price']:.0f})", callback_data=cb_data)
    return line, btn

async def _render_explore_deals(message, origin: str, region: str, deals: Dict[str, Any] | List[Dict[str, Any]]) -> None:
    if not deals:
        await message.reply_text("❌ No flight deals found matching your criteria.")
        return

    msg_lines = [f"🌟 **Top Flight Deals for {origin} → {region.upper().replace('_', ' ')}**\n"]
    buttons = []

    if isinstance(deals, dict):
        discount_deals = deals.get("discount_deals", [])
        cheapest_deals = deals.get("cheapest_deals", [])

        button_idx = 1
        if discount_deals:
            msg_lines.append("💥 **TOP DISCOUNTED DEALS (% OFF)**")
            for d in discount_deals:
                line, btn = _format_deal_item(d, button_idx, show_percentage=True)
                msg_lines.append(line)
                buttons.append([InlineKeyboardButton(f"🔔 Track #{button_idx} ({d['destination_code']} €{d['price']:.0f})", callback_data=btn.callback_data)])
                button_idx += 1

        if cheapest_deals:
            msg_lines.append("\n💶 **CHEAPEST OVERALL FLIGHTS (€)**")
            for d in cheapest_deals:
                line, btn = _format_deal_item(d, button_idx, show_percentage=False)
                msg_lines.append(line)
                buttons.append([InlineKeyboardButton(f"🔔 Track #{button_idx} ({d['destination_code']} €{d['price']:.0f})", callback_data=btn.callback_data)])
                button_idx += 1
    else:
        for idx, d in enumerate(deals, start=1):
            line, btn = _format_deal_item(d, idx, show_percentage=False)
            msg_lines.append(line)
            buttons.append([btn])

    await message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@restricted
async def track_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """1-Tap Callback button handler to quickly track an explored flight deal."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    parts = query.data.split("_")
    if len(parts) < 6:
        await query.answer("❌ Invalid deal tracking data.", show_alert=True)
        return

    origin, dest, dep_date, deal_price = parts[2], parts[3], parts[4], float(parts[5])
    target_budget = round(deal_price * 0.90, 2)

    active_count = await db_manager.get_active_trackers_count(user_id)
    if active_count >= MAX_TRACKERS_PER_USER:
        await query.answer(f"⚠️ Limit reached ({MAX_TRACKERS_PER_USER} active trackers max).", show_alert=True)
        return

    if await db_manager.has_active_tracker(user_id, origin, dest, dep_date):
        await query.answer(f"ℹ️ You are already tracking {origin} → {dest} on {dep_date}!", show_alert=True)
        return

    tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=origin,
        origin_name=origin,
        destination_code=dest,
        destination_name=dest,
        departure_date=dep_date,
        max_budget=target_budget,
        frequency_hours=6
    )

    from daemon.scheduler import schedule_tracker_job
    schedule_tracker_job(context.job_queue, tracker_id, frequency_hours=6)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if query.message:
        await query.message.reply_text(
            f"✅ **Deal Tracked!**\n\n"
            f"🔔 Created Tracker #{tracker_id} for **{origin} ✈️ {dest}** on **{dep_date}**\n"
            f"🎯 Target Budget: **€{target_budget:.2f}** (10% below deal price €{deal_price:.2f})\n"
            f"⏰ Polling frequency: Every 6 hours",
            parse_mode="Markdown"
        )
