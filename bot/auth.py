import logging
from html import escape
from typing import Optional

from telegram import InlineKeyboardMarkup, Update, User
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.keyboards import button
from bot.services import get_services
from config import MAX_TRACKERS_PER_USER, MEMBER_MAX_ACTIVE, MEMBER_MAX_RANGE_DAYS, get_allowed_users
from database.db import Database
from database.models import DENIED, PENDING
from utils.date_parser import MAX_RANGE_DAYS

logger = logging.getLogger(__name__)

REQUESTED = "📨 <b>Access requested.</b> You'll get a message here as soon as you're approved."
WAITING = "⏳ Your access request is still waiting for approval."
DENIED_TEXT = "⛔ <b>Access denied</b>: you are not authorized to use this bot."
EDITED = "✏️ I don't act on edited messages. Send it again as a new message."


def admin_id() -> Optional[int]:
    """The first ALLOWED_USERS entry approves access requests."""
    allowed = get_allowed_users()
    return allowed[0] if allowed else None


def max_active(user_id: int) -> int:
    """How many trackers and digests a user may have active at once."""
    return MAX_TRACKERS_PER_USER if user_id == admin_id() else MEMBER_MAX_ACTIVE


def max_range_days(user_id: int) -> int:
    """The longest date range (or days ahead) a user may search."""
    return MAX_RANGE_DAYS if user_id == admin_id() else MEMBER_MAX_RANGE_DAYS


def limit_reached(user_id: int) -> str:
    return (f"⚠️ You already have {max_active(user_id)} active trackers and digests, the most you can have. "
            "Pause or delete one in /mytracks first.")


async def is_allowed(db: Database, user_id: int) -> bool:
    """Everyone in ALLOWED_USERS, plus everyone the admin approved."""
    return user_id in get_allowed_users() or await db.is_approved(user_id)


def describe_user(user_id: int, username: Optional[str], full_name: Optional[str]) -> str:
    handle = f" ({escape(username)})" if username else ""
    return f"{escape(full_name or 'Unknown')}{handle} · ID <code>{user_id}</code>"


def decision_buttons(user_id: int, where: str) -> list:
    """Approve/Deny for one user; where is 'r' (request message) or 'l' (the /users list)."""
    return [button("✅ Approve", f"acc:ok:{user_id}:{where}"), button("❌ Deny", f"acc:no:{user_id}:{where}")]


async def auth_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs before every other handler; stops updates from people who don't have access,
    and edited messages from everyone.

    Someone new who writes to the bot gets an access request sent to the admin.
    """
    user = update.effective_user
    allowed = bool(user) and await is_allowed(get_services(context).db, user.id)
    if update.edited_message:
        # Telegram sends edits as their own updates; running them would repeat (or break) the original.
        if allowed:
            await update.edited_message.reply_text(EDITED)
        raise ApplicationHandlerStop
    if allowed:
        return
    if update.message or update.callback_query:
        await _handle_outsider(update, context)
    raise ApplicationHandlerStop


async def _handle_outsider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    known = await get_services(context).db.get_user(user.id) if user else None
    if known and known.status == DENIED:
        # They were told when denied; stay silent, so spamming the bot does nothing.
        if update.callback_query:
            await update.callback_query.answer()
        return

    if update.callback_query:
        await update.callback_query.answer("⛔ Access denied", show_alert=True)
        return

    db = get_services(context).db
    admin = admin_id()
    if user and admin and await db.request_access(user.id, _handle(user), user.full_name):
        await _send_request(context, admin, user, update.message.text or "")
        await update.message.reply_text(REQUESTED)
        return
    await update.message.reply_text(WAITING if known and known.status == PENDING else DENIED_TEXT)


async def _send_request(context: ContextTypes.DEFAULT_TYPE, admin: int, user: User, attempted: str) -> None:
    text = (f"🙋 <b>Access request</b>\n\n👤 {describe_user(user.id, _handle(user), user.full_name)}\n"
            f"💬 <b>First message</b>: <code>{escape(attempted)}</code>")
    try:
        await context.bot.send_message(admin, text,
                                       reply_markup=InlineKeyboardMarkup([decision_buttons(user.id, "r")]))
    except Exception:
        logger.warning("Could not send the access request to the admin", exc_info=True)


def _handle(user: Optional[User]) -> Optional[str]:
    return f"@{user.username}" if user and user.username else None

