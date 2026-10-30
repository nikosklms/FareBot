import json
import logging
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.services import get_services
from config import LOGS_DIR, get_allowed_users

logger = logging.getLogger(__name__)

UNAUTHORIZED_LOG = LOGS_DIR / "unauthorized_access.log"


async def auth_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs before every other handler; stops updates from users not in ALLOWED_USERS."""
    user = update.effective_user
    allowed = get_allowed_users()
    if user and user.id in allowed:
        return

    if update.message or update.callback_query:
        await _report_unauthorized(update, context, allowed)
    raise ApplicationHandlerStop


async def _report_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE, allowed: list[int]) -> None:
    user = update.effective_user
    username = f"@{user.username}" if user and user.username else "No username"
    full_name = user.full_name if user else "Unknown"
    if update.message:
        attempted = update.message.text or ""
    else:
        attempted = update.callback_query.data or ""

    _write_log(UNAUTHORIZED_LOG, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id if user else None,
        "username": username,
        "full_name": full_name,
        "input": attempted,
    })

    try:
        await get_services(context).db.log_unauthorized_attempt(
            user.id if user else None, username, full_name, attempted
        )
    except Exception:
        logger.exception("Failed to record unauthorized attempt in the database")

    if allowed:
        try:
            await context.bot.send_message(
                chat_id=allowed[0],
                text=(
                    "⚠️ <b>Unauthorized access attempt</b>\n\n"
                    f"👤 <b>User</b>: {escape(username)} (ID: <code>{user.id if user else '?'}</code>)\n"
                    f"📛 <b>Name</b>: {escape(full_name)}\n"
                    f"💬 <b>Input</b>: <code>{escape(attempted)}</code>"
                ),
            )
        except Exception:
            logger.warning("Could not send unauthorized-access alert to admin", exc_info=True)

    if update.message:
        await update.message.reply_text("⛔ <b>Access denied</b>: you are not authorized to use this bot.")
    else:
        await update.callback_query.answer("⛔ Access denied", show_alert=True)


def _write_log(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n")
    except OSError:
        logger.exception("Failed to write unauthorized access log")
