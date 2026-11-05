"""/mytracks: list, pause, resume and delete trackers and digests (editing lives in edit.py).

The admin can do the same to anyone's (/mytracks <ID>, or from /limits); the owner's limits don't apply
to the admin, and the owner is told about each change.

Callback data: 'dash:<action>:<kind>:<id>' with kind 't' (tracker) or 'd' (digest).
"""
import asyncio
import logging
from typing import Optional, Union

from telegram import InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.formatting import digest_card, tracker_card
from bot.keyboards import button
from bot.auth import admin_id, describe_user, is_allowed, limit_reached, max_active, parse_user_id
from bot.services import Services, get_services
from daemon.scheduler import schedule_digest, schedule_tracker, unschedule_digest, unschedule_tracker
from database.models import ACTIVE, EXPIRED, PAUSED, Digest, Tracker

logger = logging.getLogger(__name__)

TRACKER, DIGEST = "t", "d"
Item = Union[Tracker, Digest]
EDIT_NOTE_DELAY = 30  # seconds after the admin's last edit, so several edits make one message


def item_buttons(kind: str, item: Item) -> InlineKeyboardMarkup:
    row = []
    if item.status == ACTIVE:
        row.append(button("⏸ Pause", f"dash:pause:{kind}:{item.id}"))
    elif item.status == PAUSED:
        row.append(button("▶️ Resume", f"dash:resume:{kind}:{item.id}"))
    row.append(button("✏️ Edit", f"dash:edit:{kind}:{item.id}"))
    row.append(button("🗑️ Delete", f"dash:del:{kind}:{item.id}"))
    return InlineKeyboardMarkup([row, [button("🔗 Share", f"sh:link:{kind}:{item.id}")]])


def item_card(kind: str, item: Item) -> str:
    return tracker_card(item) if kind == TRACKER else digest_card(item)


async def send_items(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int,
                     header: Optional[str] = None) -> bool:
    """A card with buttons for each of a user's trackers and digests, after header if given;
    False (and nothing sent) if they have none."""
    db = get_services(context).db
    items = [(TRACKER, t) for t in await db.list_trackers(user_id)] + [(DIGEST, d) for d in await db.list_digests(user_id)]
    if items and header:
        await _send_paced(context, chat_id, header)
    for kind, item in items:
        await _send_paced(context, chat_id, item_card(kind, item), item_buttons(kind, item))
    return bool(items)


async def _send_paced(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str,
                      reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """Send one of many messages in a row; if Telegram says to slow down, wait as long as it asks and retry."""
    for _ in range(3):
        try:
            await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
            return
        except RetryAfter as e:
            wait = e.retry_after
            await asyncio.sleep(wait.total_seconds() if hasattr(wait, "total_seconds") else wait)
    await context.bot.send_message(chat_id, text, reply_markup=reply_markup)


async def send_someones_items(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    """For the admin: someone else's trackers and digests, with the usual buttons."""
    db = get_services(context).db
    user = await db.get_user(user_id)
    who = describe_user(user_id, user and user.username, user and user.full_name)
    told = ("They get a message whenever you change one." if await is_allowed(db, user_id)
            else "They don't have access anymore, so they won't be told about changes.")
    header = f"📋 <b>Trackers and digests</b> of {who}. {told}"
    if not await send_items(context, chat_id, user_id, header):
        await context.bot.send_message(chat_id, f"📋 {who} has no trackers or digests.")


async def mytracks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = target = update.effective_user.id
    if context.args:
        if user_id != admin_id():
            await update.message.reply_text("Only the bot's admin can see someone else's trackers and digests.")
            return
        target = parse_user_id(context.args[0]) if len(context.args) == 1 else None
        if target is None:
            await update.message.reply_text("❌ Use <code>/mytracks</code>, or <code>/mytracks ID</code> for "
                                            "someone else's (IDs are in /users).")
            return
    if target != user_id:
        await send_someones_items(context, update.effective_chat.id, target)
    elif not await send_items(context, update.effective_chat.id, user_id):
        await update.message.reply_text("📋 You have no trackers or digests yet. Start one with /track or /digest.")


async def load_owned(services: Services, kind: str, item_id: int, user_id: int) -> Optional[Item]:
    """The item, if user_id owns it or is the admin."""
    item = await (services.db.get_tracker(item_id) if kind == TRACKER else services.db.get_digest(item_id))
    return item if item and user_id in (item.user_id, admin_id()) else None


async def tell_owner(context: ContextTypes.DEFAULT_TYPE, actor_id: int, kind: str, item: Item, what: str,
                     buttons: bool = True) -> None:
    """When the admin changes someone else's tracker or digest, tell its owner what happened
    (unless they no longer have access: they couldn't use the buttons)."""
    if actor_id == item.user_id or not await is_allowed(get_services(context).db, item.user_id):
        return
    try:
        await context.bot.send_message(item.user_id, f"{what}\n\n{item_card(kind, item)}",
                                       reply_markup=item_buttons(kind, item) if buttons else None)
    except TelegramError:
        logger.info("Could not tell user %s about the admin's change to %s", item.user_id, label_for(kind, item.id))


def tell_owner_after_edits(context: ContextTypes.DEFAULT_TYPE, actor_id: int, kind: str, item: Item) -> None:
    """Like tell_owner, for the editor: one message with the final card once the admin stops editing."""
    if actor_id == item.user_id:
        return
    name = f"tell:{kind}:{item.id}"
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    context.job_queue.run_once(_tell_edited, EDIT_NOTE_DELAY, data=(kind, item.id), name=name)


async def _tell_edited(context: ContextTypes.DEFAULT_TYPE) -> None:
    kind, item_id = context.job.data
    db = get_services(context).db
    item = await (db.get_tracker(item_id) if kind == TRACKER else db.get_digest(item_id))
    if item:  # deleted meanwhile: the owner was told about that instead
        await tell_owner(context, admin_id(), kind, item, f"✏️ The admin changed your {label_for(kind, item_id)}.")


def label_for(kind: str, item_id: int) -> str:
    return f"Tracker #{item_id}" if kind == TRACKER else f"Digest #{item_id}"


async def set_active(services: Services, context: ContextTypes.DEFAULT_TYPE, kind: str, item: Item,
                     active: bool, actor_id: int) -> bool:
    """Pause or (re)activate an item for actor_id. Activation is refused at the owner's limit, unless
    the admin is acting on someone else's item; returns success."""
    if (active and item.status != ACTIVE and actor_id == item.user_id
            and await services.db.count_active(item.user_id) >= await max_active(services.db, item.user_id)):
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

    actor = query.from_user.id
    if action in ("pause", "resume") and item.status == EXPIRED:
        # A button from before it expired: its dates have passed, so only new dates bring it back.
        await query.edit_message_text(f"⌛ {label} has expired: its dates have passed. Edit its dates to use it again.",
                                      reply_markup=item_buttons(kind, item))
        return
    if action == "pause":
        await set_active(services, context, kind, item, False, actor)
        await query.edit_message_text(f"⏸ {label} paused.", reply_markup=item_buttons(kind, item))
        await tell_owner(context, actor, kind, item, f"⏸ The admin paused your {label}.")
    elif action == "resume":
        if not await set_active(services, context, kind, item, True, actor):
            await query.message.reply_text(await limit_reached(services.db, item.user_id))
            return
        await query.edit_message_text(f"▶️ {label} resumed.", reply_markup=item_buttons(kind, item))
        await tell_owner(context, actor, kind, item, f"▶️ The admin resumed your {label}.")
    elif action == "del":
        if kind == TRACKER:
            await services.db.delete_tracker(item.id)
            unschedule_tracker(context.job_queue, item.id)
        else:
            await services.db.delete_digest(item.id)
            unschedule_digest(context.job_queue, item.id)
        await query.edit_message_text(f"🗑️ {label} deleted.")
        await tell_owner(context, actor, kind, item, f"🗑️ The admin deleted your {label}.", buttons=False)


dashboard_handler = CallbackQueryHandler(dashboard_pressed, pattern=r"^dash:(pause|resume|del):[td]:\d+$")
