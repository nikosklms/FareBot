"""/mytracks: list, pause, resume, delete and edit the budget of trackers and digests.

Callback data: 'dash:<action>:<kind>:<id>' with kind 't' (tracker) or 'd' (digest).
"""
from typing import Optional, Union

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.formatting import budget_text, digest_card, eur, tracker_card
from bot.keyboards import button
from bot.services import Services, get_services
from bot.wizard import PENDING_BUDGET_KEY
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
    row.append(button("✏️ Budget", f"dash:budget:{kind}:{item.id}"))
    row.append(button("🗑️ Delete", f"dash:del:{kind}:{item.id}"))
    return InlineKeyboardMarkup([row])


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


async def _load_owned(services: Services, kind: str, item_id: int, user_id: int) -> Optional[Item]:
    item = await (services.db.get_tracker(item_id) if kind == TRACKER else services.db.get_digest(item_id))
    return item if item and item.user_id == user_id else None


def _label(kind: str, item_id: int) -> str:
    return f"Tracker #{item_id}" if kind == TRACKER else f"Digest #{item_id}"


async def _set_active(services: Services, context: ContextTypes.DEFAULT_TYPE, kind: str, item: Item, active: bool) -> None:
    item.status = ACTIVE if active else PAUSED
    if kind == TRACKER:
        await services.db.set_tracker_status(item.id, item.status)
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


async def dashboard_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, kind, raw_id = query.data.split(":")
    services = get_services(context)
    item = await _load_owned(services, kind, int(raw_id), query.from_user.id)
    if not item:
        await query.answer("This item no longer exists.", show_alert=True)
        return
    await query.answer()
    label = _label(kind, item.id)

    if action == "pause":
        await _set_active(services, context, kind, item, active=False)
        await query.edit_message_text(f"⏸ {label} paused.", reply_markup=item_buttons(kind, item))
    elif action == "resume":
        await _set_active(services, context, kind, item, active=True)
        await query.edit_message_text(f"▶️ {label} resumed.", reply_markup=item_buttons(kind, item))
    elif action == "del":
        if kind == TRACKER:
            await services.db.delete_tracker(item.id)
            unschedule_tracker(context.job_queue, item.id)
        else:
            await services.db.delete_digest(item.id)
            unschedule_digest(context.job_queue, item.id)
        await query.edit_message_text(f"🗑️ {label} deleted.")
    elif action == "budget":
        context.user_data[PENDING_BUDGET_KEY] = (kind, item.id)
        hint = " Send <code>0</code> for any budget." if kind == DIGEST else ""
        await query.message.reply_text(
            f"✏️ <b>New budget for {label}</b> (now {budget_text(item.max_budget)})\n\n"
            f"Send the new maximum price in EUR, e.g. <code>45</code>.{hint}"
        )


async def budget_typed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text after tapping 'Budget'. Ignored when no budget edit is pending."""
    pending = context.user_data.get(PENDING_BUDGET_KEY)
    if not pending:
        return
    kind, item_id = pending
    try:
        budget = float(update.message.text.strip().replace("€", ""))
    except ValueError:
        budget = -1
    if budget < 0 or (budget == 0 and kind == TRACKER):
        await update.message.reply_text("❌ That's not a valid budget. Send a number like <code>45</code>, or /cancel.")
        return
    context.user_data.pop(PENDING_BUDGET_KEY)

    services = get_services(context)
    item = await _load_owned(services, kind, item_id, update.effective_user.id)
    if not item:
        await update.message.reply_text("This item no longer exists.")
        return

    label = _label(kind, item_id)
    if kind == DIGEST:
        await services.db.set_digest_budget(item_id, budget or None)
        await update.message.reply_text(f"✅ {label} budget set to <b>{budget_text(budget)}</b>.")
        return

    await services.db.set_tracker_budget(item_id, budget)
    item.max_budget = budget
    note = ""
    if item.status == PAUSED:
        await _set_active(services, context, kind, item, active=True)
        note = " It was paused, so I've resumed it."
    await update.message.reply_text(f"✅ {label} budget set to <b>{eur(budget)}</b>.{note}")


dashboard_handler = CallbackQueryHandler(dashboard_pressed, pattern=r"^dash:(pause|resume|del|budget):[td]:\d+$")
