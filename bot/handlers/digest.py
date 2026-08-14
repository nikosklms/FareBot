from telegram import Update
from telegram.ext import ContextTypes
from config import DB_PATH
from database.db import DatabaseManager
from bot.handlers.auth import restricted
from daemon.scheduler import schedule_digest_job

db_manager = DatabaseManager(DB_PATH)

@restricted
async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /digest command."""
    args = context.args or []
    origin = args[0].upper() if len(args) > 0 else "ATH"
    region = args[1].lower() if len(args) > 1 else "europe"
    
    budget = None
    if len(args) > 2 and args[2].isdigit():
        budget = float(args[2])

    schedule_str = args[3] if len(args) > 3 else "Sunday at 15:00"
    user_id = update.effective_user.id

    from datetime import datetime, timedelta, timezone
    dep_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    # Deduplication check
    if await db_manager.has_active_digest(user_id, origin, f"REGION:{region.upper()}", dep_date):
        await update.message.reply_text(f"⚠️ You already have an active digest for **{origin} → {region.upper()}**!", parse_mode="Markdown")
        return

    digest_tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=origin,
        origin_name=origin,
        destination_code=f"REGION:{region.upper()}",
        destination_name=f"{region.capitalize()} Digest",
        departure_date=dep_date,
        max_budget=budget or 0.0,
        frequency_hours=168
    )

    schedule_digest_job(
        job_queue=context.job_queue,
        tracker_id=digest_tracker_id,
        user_id=user_id,
        origin=origin,
        region=region,
        budget=budget or 0.0,
        schedule_str=schedule_str
    )

    budget_str = f"€{budget:.2f}" if budget else "Any Budget"
    await update.message.reply_text(
        f"✅ **Weekly Digest Scheduled!**\n\n"
        f"🗞️ **Digest #{digest_tracker_id}**: {origin} ✈️ {region.upper()}\n"
        f"🎯 **Budget**: {budget_str}\n"
        f"⏰ **Frequency**: Every {schedule_str}\n\n"
        f"You can view or manage your scheduled digest anytime in `/mytracks`!",
        parse_mode="Markdown"
    )
