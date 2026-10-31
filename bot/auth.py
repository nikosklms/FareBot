import json
import logging
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardMarkup, Update, User
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.keyboards import button
from bot.services import get_services
from config import LOGS_DIR, get_allowed_users
from database.db import Database
from database.models import DENIED, PENDING

logger = logging.getLogger(__name__)

UNAUTHORIZED_LOG = LOGS_DIR / "unauthorized_access.log"

REQUESTED = "📨 <b>Access requested.</b> You'll get a message here as soon as you're approved."
WAITING = "⏳ Your access request is still waiting for approval."
DENIED_TEXT = "⛔ <b>Access denied</b>: you are not authorized to use this bot."


def admin_id() -> Optional[int]:
    """The first ALLOWED_USERS entry approves access requests."""
    allowed = get_allowed_users()
    return allowed[0] if allowed else None


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
    """Runs before every other handler; stops updates from people who don't have access.

    Someone new who writes to the bot gets an access request sent to the admin.
    """
    user = update.effective_user
    if user and await is_allowed(get_services(context).db, user.id):
        return
    if update.message or update.callback_query:
        await _handle_outsider(update, context)
    raise ApplicationHandlerStop


async def _handle_outsider(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    known = await get_services(context).db.get_user(user.id) if user else None
    if known and known.status == DENIED:
        # They were told when denied; stay silent and log nothing, so spamming the bot does nothing.
        if update.callback_query:
            await update.callback_query.answer()
        return

    attempted = (update.message.text if update.message else update.callback_query.data) or ""
    await _record_attempt(context, user, attempted)

    if update.callback_query:
        await update.callback_query.answer("⛔ Access denied", show_alert=True)
        return

    db = get_services(context).db
    admin = admin_id()
    if user and admin and await db.request_access(user.id, _handle(user), user.full_name):
        await _send_request(context, admin, user, attempted)
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


async def _record_attempt(context: ContextTypes.DEFAULT_TYPE, user: Optional[User], attempted: str) -> None:
    username = _handle(user) or "No username"
    full_name = user.full_name if user else "Unknown"
    _write_log(UNAUTHORIZED_LOG, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id if user else None,
        "username": username,
        "full_name": full_name,
        "input": attempted,
    })
    try:
        await get_services(context).db.log_unauthorized_attempt(user.id if user else None, username, full_name,
                                                                attempted)
    except Exception:
        logger.exception("Failed to record unauthorized attempt in the database")


def _write_log(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n")
    except OSError:
        logger.exception("Failed to write unauthorized access log")
