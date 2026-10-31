"""/mytracks: list, pause, resume and delete trackers and digests (editing lives in edit.py).

Callback data: 'dash:<action>:<kind>:<id>' with kind 't' (tracker) or 'd' (digest).
"""
from typing import Optional, Union

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.formatting import digest_card, tracker_card
from bot.keyboards import button
from bot.auth import limit_reached, max_active
from bot.services import Services, get_services
from daemon.scheduler import schedule_digest, schedule_tracker, unschedule_digest, unschedule_tracker
from database.models import ACTIVE, PAUSED, Digest, Tracker

TRACKER, DIGEST = "t", "d"
Item = Union[Tracker, Digest]


def item_buttons(kind: str, item: Item) -> InlineKeyboardMarkup:
    row = []
    if item.status == ACTIVE:
        row.append(button("⏸ Pause", f"dash:pause:{kind}:{item.id}"))
    elif item.status == PAUSED:
        row.append(button("▶️ Resume", f"dash:resume:{kind}:{item.id}"))
    row.append(button("✏️ Edit", f"dash:edit:{kind}:{item.id}"))
    row.append(button("🗑️ Delete", f"dash:del:{kind}:{item.id}"))
    return InlineKeyboardMarkup([row, [button("🔗 Share", f"sh:link:{kind}:{item.id}")]])


async def mytracks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_services(context).db
    user_id = update.effective_user.id
    trackers = await db.list_trackers(user_id)
    digests = await db.list_digests(user_id)
    if not trackers and not digests:
        await update.message.reply_text("📋 You have no trackers or digests yet. Start one with /track or /digest.")
        return
    for tracker in trackers:
        await update.message.reply_text(tracker_card(tracker), reply_markup=item_buttons(TRACKER, tracker))
    for digest in digests:
        await update.message.reply_text(digest_card(digest), reply_markup=item_buttons(DIGEST, digest))


async def load_owned(services: Services, kind: str, item_id: int, user_id: int) -> Optional[Item]:
    item = await (services.db.get_tracker(item_id) if kind == TRACKER else services.db.get_digest(item_id))
    return item if item and item.user_id == user_id else None


def label_for(kind: str, item_id: int) -> str:
    return f"Tracker #{item_id}" if kind == TRACKER else f"Digest #{item_id}"


async def set_active(services: Services, context: ContextTypes.DEFAULT_TYPE, kind: str, item: Item,
                     active: bool) -> bool:
    """Pause or (re)activate an item. Activation is refused at the per-user limit; returns success."""
    if active and item.status != ACTIVE and await services.db.count_active(item.user_id) >= max_active(item.user_id):
        return False
    item.status = ACTIVE if active else PAUSED
    if kind == TRACKER:
        changes = {"status": item.status, **({"consecutive_failures": 0} if active else {})}
        await services.db.update_tracker(item.id, **changes)
        item.consecutive_failures = 0 if active else item.consecutive_failures
        if active:
            schedule_tracker(context.job_queue, item)
        else:
            unschedule_tracker(context.job_queue, item.id)
    else:
        await services.db.set_digest_status(item.id, item.status)
        if active:
            schedule_digest(context.job_queue, item, services.timezone)
        else:
            unschedule_digest(context.job_queue, item.id)
    return True


async def dashboard_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, kind, raw_id = query.data.split(":")
    services = get_services(context)
    item = await load_owned(services, kind, int(raw_id), query.from_user.id)
    if not item:
        await query.answer("This item no longer exists.", show_alert=True)
        return
    await query.answer()
    label = label_for(kind, item.id)

    if action == "pause":
        await set_active(services, context, kind, item, active=False)
        await query.edit_message_text(f"⏸ {label} paused.", reply_markup=item_buttons(kind, item))
    elif action == "resume":
        if not await set_active(services, context, kind, item, active=True):
            await query.message.reply_text(limit_reached(item.user_id))
            return
        await query.edit_message_text(f"▶️ {label} resumed.", reply_markup=item_buttons(kind, item))
    elif action == "del":
        if kind == TRACKER:
            await services.db.delete_tracker(item.id)
            unschedule_tracker(context.job_queue, item.id)
        else:
            await services.db.delete_digest(item.id)
            unschedule_digest(context.job_queue, item.id)
        await query.edit_message_text(f"🗑️ {label} deleted.")


dashboard_handler = CallbackQueryHandler(dashboard_pressed, pattern=r"^dash:(pause|resume|del):[td]:\d+$")
