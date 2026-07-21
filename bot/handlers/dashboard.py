from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH
from database.db import DatabaseManager

db_manager = DatabaseManager(DB_PATH)

async def mytracks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    trackers = await db_manager.get_user_trackers(user_id)

    if not trackers:
        await update.message.reply_text("📋 You have no active or saved flight trackers. Create one using `/newtrack`!", parse_mode="Markdown")
        return

    for t in trackers:
        status_icon = "🟢" if t["status"] == "ACTIVE" else "⏸️" if t["status"] == "PAUSED" else "🔴"
        price_text = f"€{t['last_price_found']:.2f}" if t.get("last_price_found") else "Not checked yet"
        text = (
            f"{status_icon} **Tracker #{t['id']}**\n"
            f"📍 **Route**: {t['origin_code']} ✈️ {t['destination_code']}\n"
            f"📅 **Date**: {t['departure_date']}\n"
            f"🎯 **Target Budget**: €{t['max_budget']:.2f}\n"
            f"📊 **Status**: {t['status']}\n"
            f"💶 **Last Price**: {price_text}"
        )

        buttons = []
        if t["status"] == "ACTIVE":
            buttons.append(InlineKeyboardButton("⏸ Pause", callback_data=f"dash_pause_{t['id']}"))
        elif t["status"] == "PAUSED":
            buttons.append(InlineKeyboardButton("▶️ Resume", callback_data=f"dash_resume_{t['id']}"))

        buttons.append(InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{t['id']}"))

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([buttons]))

async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("dash_pause_"):
        tracker_id = int(data.split("_")[2])
        await db_manager.update_tracker_status(tracker_id, "PAUSED")
        await query.message.edit_text(f"⏸ Tracker #{tracker_id} paused.")
    elif data.startswith("dash_resume_"):
        tracker_id = int(data.split("_")[2])
        await db_manager.update_tracker_status(tracker_id, "ACTIVE")
        await query.message.edit_text(f"▶️ Tracker #{tracker_id} resumed.")
    elif data.startswith("dash_del_"):
        tracker_id = int(data.split("_")[2])
        await db_manager.delete_tracker(tracker_id)
        await query.message.edit_text(f"🗑️ Tracker #{tracker_id} deleted.")
