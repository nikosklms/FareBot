import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from bot.handlers.auth import restricted
from services.explore_engine import run_explore_query
from services.resolver import LocationResolver

logger = logging.getLogger(__name__)
db_manager = DatabaseManager(DB_PATH)
resolver = LocationResolver()

EXPLORE_ORIGIN, EXPLORE_REGION, EXPLORE_BUDGET, EXPLORE_LIMIT = range(4)

@restricted
async def start_explore_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start interactive /explore wizard or execute one-line shortcut if args provided."""
    args = context.args or []

    # One-line shortcut execution
    if len(args) >= 2:
        origin = args[0].upper()
        region = args[1].lower()
        max_budget = float(args[2]) if len(args) > 2 and args[2].isdigit() else None
        max_results = int(args[3]) if len(args) > 3 and args[3].isdigit() else 10
        max_results = max(1, min(20, max_results))

        dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        await update.message.reply_text(
            f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}**...",
            parse_mode="Markdown"
        )
        deals = await run_explore_query(origin, region, dep_date, max_budget=max_budget, max_results=max_results)
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
        "🌍 **Explore Top Flight Deals Wizard**\n\n"
        "🛫 **Step 1/4**: Where are you flying from?\n"
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
        "🌍 **Step 2/4**: Select a destination region to explore:",
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
        [InlineKeyboardButton("€50", callback_data="expl_bud_50"), InlineKeyboardButton("€100", callback_data="expl_bud_100"), InlineKeyboardButton("€150", callback_data="expl_bud_150")],
        [InlineKeyboardButton("€200", callback_data="expl_bud_200"), InlineKeyboardButton("Any Budget 💶", callback_data="expl_bud_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    await query.message.edit_text(
        f"✅ Region set to: **{region.upper().replace('_', ' ')}**\n\n"
        "🎯 **Step 3/4**: Select maximum target budget (or type amount in EUR, e.g. '80'):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXPLORE_BUDGET

@restricted
async def handle_explore_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        val = float(text)
        budget = val if val > 0 else None
    except ValueError:
        await update.message.reply_text("❌ Invalid budget amount. Please type a positive number (e.g. '80') or tap a button below.")
        return EXPLORE_BUDGET

    context.user_data["explore_budget"] = budget
    return await _ask_explore_limit(update.message, context)

@restricted
async def select_explore_budget_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = float(query.data.split("_")[2])
    context.user_data["explore_budget"] = val if val > 0 else None
    return await _ask_explore_limit(query.message, context, is_callback=True)

async def _ask_explore_limit(message, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False) -> int:
    budget = context.user_data.get("explore_budget")
    bud_str = f"€{budget:.2f}" if budget else "Any Budget"

    buttons = [
        [InlineKeyboardButton("5", callback_data="expl_lim_5"), InlineKeyboardButton("10 (Default)", callback_data="expl_lim_10")],
        [InlineKeyboardButton("15", callback_data="expl_lim_15"), InlineKeyboardButton("20", callback_data="expl_lim_20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]
    ]

    msg_text = (
        f"✅ Budget set to: **{bud_str}**\n\n"
        "📊 **Step 4/4**: How many top flight deal results would you like to see? (1 to 20, default 10):"
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
    max_budget = context.user_data.get("explore_budget")

    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    status_msg = f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}**..."

    if is_callback:
        await message.edit_text(status_msg, parse_mode="Markdown")
    else:
        await message.reply_text(status_msg, parse_mode="Markdown")

    deals = await run_explore_query(origin, region, dep_date, max_budget=max_budget, max_results=limit)
    await _render_explore_deals(message, origin, region, deals)
    context.user_data.clear()
    return ConversationHandler.END

async def _render_explore_deals(message, origin: str, region: str, deals: List[Dict[str, Any]]) -> None:
    if not deals:
        await message.reply_text("❌ No flight deals found matching your criteria.")
        return

    msg_lines = [f"🌟 **Top Flight Deals for {origin} → {region.upper().replace('_', ' ')}**\n"]
    buttons = []

    for idx, d in enumerate(deals, start=1):
        disc_text = f" (💥 {d['discount_pct']:.0f}% OFF!)" if d.get("discount_pct", 0) > 15 else ""
        msg_lines.append(
            f"{idx}. **{d['origin_code']} ✈️ {d['destination_code']} ({d['destination_name']})**\n"
            f"💶 **€{d['price']:.2f}**{disc_text} | 📅 {d['departure_date']} ({d['airline']})\n"
        )
        cb_data = f"track_deal_{d['origin_code']}_{d['destination_code']}_{d['departure_date']}_{d['price']}"
        buttons.append([InlineKeyboardButton(f"🔔 Track Deal #{idx} (€{d['price']:.0f})", callback_data=cb_data)])

    await message.reply_text("\n".join(msg_lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def track_deal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for 1-tap deal tracking."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    if not data.startswith("track_deal_"):
        return

    parts = data.split("_")
    if len(parts) < 5:
        await query.answer("❌ Invalid deal parameters.")
        return

    origin = parts[2]
    destination = parts[3]
    dep_date = parts[4]
    price = float(parts[5])

    # Check deduplication guard
    if await db_manager.has_active_tracker(user_id, origin, destination, dep_date):
        await query.answer(f"⚠️ You are already tracking {origin} → {destination} for {dep_date}!", show_alert=True)
        return

    # Check active trackers limit
    active_count = await db_manager.get_active_trackers_count(user_id)
    if active_count >= MAX_TRACKERS_PER_USER:
        await query.answer(f"⚠️ Limit reached ({MAX_TRACKERS_PER_USER} active trackers).", show_alert=True)
        return

    # Target price rule: -10% buffer below deal price
    target_budget = round(price * 0.9, 2)

    t_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=origin,
        origin_name=origin,
        destination_code=destination,
        destination_name=destination,
        departure_date=dep_date,
        max_budget=target_budget
    )

    await query.answer("✅ Tracker created!")
    await query.message.reply_text(
        f"✅ **Deal Tracked!**\n\n"
        f"Created Tracker #{t_id} for **{origin} ✈️ {destination}**\n"
        f"📅 **Departure**: {dep_date}\n"
        f"🎯 **Target Budget**: **€{target_budget:.2f}** (-10% below deal price)",
        parse_mode="Markdown"
    )

    # Update button markup state to ✅ Tracked!
    reply_markup = query.message.reply_markup
    if reply_markup:
        new_keyboard = []
        for row in reply_markup.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data == data:
                    new_row.append(InlineKeyboardButton("✅ Tracked!", callback_data="cal_ignore"))
                else:
                    new_row.append(btn)
            new_keyboard.append(new_row)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
