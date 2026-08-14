from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager
from bot.handlers.auth import restricted
from services.explore_engine import run_explore_query

db_manager = DatabaseManager(DB_PATH)

@restricted
async def explore_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /explore command."""
    args = context.args or []
    origin = args[0].upper() if len(args) > 0 else "ATH"
    region = args[1].lower() if len(args) > 1 else "europe"
    
    max_budget = None
    if len(args) > 2 and args[2].isdigit():
        max_budget = float(args[2])

    from datetime import datetime, timedelta, timezone
    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    await update.message.reply_text(f"🔍 Exploring top flight deals from **{origin}** to **{region.upper()}**...", parse_mode="Markdown")

    deals = await run_explore_query(origin, region, dep_date, max_budget=max_budget)
    if not deals:
        await update.message.reply_text("❌ No flight deals found matching your criteria.")
        return

    msg_lines = [f"🌟 **Top Flight Deals for {origin} → {region.upper()}**\n"]
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

    await db_manager.create_tracker(
        user_id=user_id,
        origin_code=origin,
        origin_name=origin,
        destination_code=destination,
        destination_name=destination,
        departure_date=dep_date,
        max_budget=target_budget
    )

    await query.answer(f"✅ Tracker created for {origin} → {destination} (Budget: €{target_budget:.2f})!")

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
