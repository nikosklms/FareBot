from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from bot.handlers.auth import restricted
from services.explore_engine import run_explore_query

db_manager = DatabaseManager(DB_PATH)

@restricted
@restricted
async def explore_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /explore command."""
    args = context.args or []

    if not args:
        buttons = [
            [InlineKeyboardButton("🇪🇺 Europe", callback_data="expl_ATH_europe"), InlineKeyboardButton("🏝️ Greek Islands", callback_data="expl_ATH_islands")],
            [InlineKeyboardButton("🕌 Middle East", callback_data="expl_ATH_middle_east"), InlineKeyboardButton("⛩️ Asia", callback_data="expl_ATH_asia")],
            [InlineKeyboardButton("🌍 Africa", callback_data="expl_ATH_africa"), InlineKeyboardButton("🦘 Oceania", callback_data="expl_ATH_oceania")],
            [InlineKeyboardButton("💃 Latin America", callback_data="expl_ATH_latin_america"), InlineKeyboardButton("🗽 North America", callback_data="expl_ATH_north_america")]
        ]
        await update.message.reply_text(
            "🌍 **Explore Top Flight Deals**\n\n"
            "Select a region below to discover top deals from **ATH** (or use one-line syntax: `/explore [origin] [region] [budget]`):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    origin = args[0].upper() if len(args) > 0 else "ATH"
    region = args[1].lower() if len(args) > 1 else "europe"
    
    max_budget = None
    if len(args) > 2 and args[2].isdigit():
        max_budget = float(args[2])

    from datetime import datetime, timedelta, timezone
    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    await update.message.reply_text(f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}**...", parse_mode="Markdown")

    deals = await run_explore_query(origin, region, dep_date, max_budget=max_budget)
    if not deals:
        await update.message.reply_text("❌ No flight deals found matching your criteria.")
        return

    msg_lines = [f"🌟 **Top Flight Deals for {origin} → {region.upper().replace('_', ' ')}**\n"]
    buttons = []

    for idx, d in enumerate(deals[:5], start=1):
        disc_text = f" (💥 {d['discount_pct']:.0f}% OFF!)" if d.get("discount_pct", 0) > 15 else ""
        msg_lines.append(
            f"{idx}. **{d['origin_code']} ✈️ {d['destination_code']} ({d['destination_name']})**\n"
            f"💶 **€{d['price']:.2f}**{disc_text} | 📅 {d['departure_date']} ({d['airline']})\n"
        )
        cb_data = f"track_deal_{d['origin_code']}_{d['destination_code']}_{d['departure_date']}_{d['price']}"
        buttons.append([InlineKeyboardButton(f"🔔 Track Deal #{idx} (€{d['price']:.0f})", callback_data=cb_data)])

    await update.message.reply_text("\n".join(msg_lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

@restricted
async def explore_region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for region quick-selector buttons."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    origin, region = parts[1], parts[2]

    from datetime import datetime, timedelta, timezone
    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    await query.message.edit_text(f"🔍 Exploring top flight deals from **{origin}** to **{region.upper().replace('_', ' ')}**...", parse_mode="Markdown")

    deals = await run_explore_query(origin, region, dep_date)
    if not deals:
        await query.message.edit_text("❌ No flight deals found matching your criteria.")
        return

    msg_lines = [f"🌟 **Top Flight Deals for {origin} → {region.upper().replace('_', ' ')}**\n"]
    buttons = []

    for idx, d in enumerate(deals[:5], start=1):
        disc_text = f" (💥 {d['discount_pct']:.0f}% OFF!)" if d.get("discount_pct", 0) > 15 else ""
        msg_lines.append(
            f"{idx}. **{d['origin_code']} ✈️ {d['destination_code']} ({d['destination_name']})**\n"
            f"💶 **€{d['price']:.2f}**{disc_text} | 📅 {d['departure_date']} ({d['airline']})\n"
        )
        cb_data = f"track_deal_{d['origin_code']}_{d['destination_code']}_{d['departure_date']}_{d['price']}"
        buttons.append([InlineKeyboardButton(f"🔔 Track Deal #{idx} (€{d['price']:.0f})", callback_data=cb_data)])

    await query.message.edit_text("\n".join(msg_lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

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
