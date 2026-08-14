from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH
from database.db import DatabaseManager
from daemon import schedule_tracker_job, unschedule_tracker_job
from bot.handlers.auth import restricted

db_manager = DatabaseManager(DB_PATH)

@restricted
async def mytracks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    trackers = await db_manager.get_user_trackers(user_id)

    if not trackers:
        await update.message.reply_text("📋 You have no active or saved flight trackers. Create one using `/newtrack`!", parse_mode="Markdown")
        return

    for t in trackers:
        status_icon = "🟢" if t["status"] == "ACTIVE" else "⏸️" if t["status"] == "PAUSED" else "🔴"
        price_text = f"€{t['last_price_found']:.2f}" if t.get("last_price_found") else "Not checked yet"
        flight_type_text = "Direct Flights Only ✈️" if t.get("direct_only") else "Any Flights 🔄"

        is_digest = t.get("destination_code", "").startswith("REGION:")
        region_name = t["destination_code"].replace("REGION:", "") if is_digest else ""
        header_text = f"🗞️ **Weekly Digest #{t['id']}**" if is_digest else f"{status_icon} **Tracker #{t['id']}**"
        route_text = f"{t['origin_code']} ✈️ {region_name}" if is_digest else f"{t['origin_code']} ✈️ {t['destination_code']}"
        budget_disp = f"€{t['max_budget']:.2f}" if t.get("max_budget", 0) > 0 else "Any Budget"

        if is_digest:
            text = (
                f"{header_text}\n"
                f"📍 **Route**: {route_text}\n"
                f"📅 **Frequency**: Every Week (Sunday)\n"
                f"🎯 **Target Budget**: {budget_disp}\n"
                f"📊 **Status**: {t['status']}"
            )
        else:
            text = (
                f"{header_text}\n"
                f"📍 **Route**: {route_text}\n"
                f"📅 **Date**: {t['departure_date']}\n"
                f"⚙️ **Flight Type**: {flight_type_text}\n"
                f"🎯 **Target Budget**: {budget_disp}\n"
                f"📊 **Status**: {t['status']}\n"
                f"💶 **Last Price**: {price_text}"
            )

        buttons = []
        if t["status"] == "ACTIVE":
            buttons.append(InlineKeyboardButton("⏸ Pause", callback_data=f"dash_pause_{t['id']}"))
        elif t["status"] == "PAUSED":
            buttons.append(InlineKeyboardButton("▶️ Resume", callback_data=f"dash_resume_{t['id']}"))

        buttons.append(InlineKeyboardButton("✏️ Edit Budget", callback_data=f"dash_editbudget_{t['id']}"))
        buttons.append(InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{t['id']}"))

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([buttons]))

@restricted
async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data.startswith("dash_pause_"):
        tracker_id = int(data.split("_")[2])
        t = await db_manager.get_tracker_by_id(tracker_id)
        if not t or t.get("user_id") != user_id:
            await query.message.reply_text("⛔ Unauthorized or tracker not found.")
            return
        await db_manager.update_tracker_status(tracker_id, "PAUSED")
        if context.job_queue:
            unschedule_tracker_job(context.job_queue, tracker_id)
        await query.message.edit_text(f"⏸ Tracker #{tracker_id} paused.")
    elif data.startswith("dash_resume_"):
        tracker_id = int(data.split("_")[2])
        t = await db_manager.get_tracker_by_id(tracker_id)
        if not t or t.get("user_id") != user_id:
            await query.message.reply_text("⛔ Unauthorized or tracker not found.")
            return
        await db_manager.update_tracker_status(tracker_id, "ACTIVE")
        if context.job_queue:
            if t.get("destination_code", "").startswith("REGION:"):
                reg = t["destination_code"].replace("REGION:", "").lower()
                from daemon.scheduler import schedule_digest_job
                schedule_digest_job(context.job_queue, tracker_id, user_id, t["origin_code"], reg, t.get("max_budget", 0.0))
            else:
                freq = t.get("frequency_hours", 6) if t else 6
                schedule_tracker_job(context.job_queue, tracker_id, freq)
        await query.message.edit_text(f"▶️ Tracker #{tracker_id} resumed.")
    elif data.startswith("dash_editbudget_"):
        tracker_id = int(data.split("_")[2])
        t = await db_manager.get_tracker_by_id(tracker_id)
        if not t or t.get("user_id") != user_id:
            await query.message.reply_text("⛔ Unauthorized or tracker not found.")
            return
        context.user_data["edit_tracker_id"] = tracker_id
        await query.message.reply_text(f"✏️ **Edit Target Budget for Tracker #{tracker_id}**\n\nSend new target budget in EUR (e.g., `45`):", parse_mode="Markdown")
    elif data.startswith("dash_del_"):
        tracker_id = int(data.split("_")[2])
        t = await db_manager.get_tracker_by_id(tracker_id)
        if not t or t.get("user_id") != user_id:
            await query.message.reply_text("⛔ Unauthorized or tracker not found.")
            return
        await db_manager.delete_tracker(tracker_id)
        if context.job_queue:
            unschedule_tracker_job(context.job_queue, tracker_id)
        await query.message.edit_text(f"🗑️ Tracker #{tracker_id} deleted.")

@restricted
async def handle_edit_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "edit_tracker_id" not in context.user_data:
        return

    tracker_id = context.user_data.pop("edit_tracker_id")
    text = update.message.text.strip() if update.message and update.message.text else ""

    try:
        new_budget = float(text)
        if new_budget <= 0:
            await update.message.reply_text("❌ Budget must be a positive number greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid budget amount. Please send a valid number (e.g. `45`).", parse_mode="Markdown")
        return

    await db_manager.update_budget(tracker_id, new_budget)
    await update.message.reply_text(
        f"✅ **Target Budget Updated!**\n\n"
        f"Tracker #{tracker_id} target budget updated to **€{new_budget:.2f}**.",
        parse_mode="Markdown"
    )

