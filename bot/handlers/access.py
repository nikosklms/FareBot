"""Admin tools for access requests: Approve/Deny buttons and /users.

Callback data: 'acc:<ok|no|rm>:<user id>:<r|l>', where r is the request message and l is the /users list.
"""
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import admin_id, decision_buttons, describe_user
from bot.keyboards import button
from bot.services import get_services
from config import get_allowed_users
from database.db import Database
from database.models import APPROVED, DENIED, PENDING, User

logger = logging.getLogger(__name__)

ADMIN_ONLY = "Only the bot's admin can manage users."
TELL_USER = {
    APPROVED: "✅ <b>You're in!</b> Send /start to begin.",
    DENIED: "Sorry, your request to use this bot wasn't approved.",
    None: "ℹ️ Your access to this bot was removed.",
}
RESULT = {APPROVED: "✅ Approved", DENIED: "❌ Denied", None: "🚫 Removed"}


def _short_name(user: User) -> str:
    name = user.full_name or user.username or str(user.user_id)
    return name if len(name) <= 18 else name[:17] + "…"


async def users_view(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    users = await db.list_users()
    groups = {status: [u for u in users if u.status == status] for status in (PENDING, APPROVED, DENIED)}
    always = get_allowed_users()
    lines = ["👥 <b>Users</b>", "", f"👑 <b>Always allowed</b> (ALLOWED_USERS): {len(always)}"]
    for status, title in ((PENDING, "⏳ <b>Waiting</b>"), (APPROVED, "✅ <b>Approved</b>"), (DENIED, "❌ <b>Denied</b>")):
        lines += ["", f"{title} ({len(groups[status])})"]
        lines += [f"• {describe_user(u.user_id, u.username, u.full_name)}" for u in groups[status]] or ["• nobody"]

    rows = [decision_buttons(u.user_id, "l") for u in groups[PENDING]]
    rows += [[button(f"🚫 Remove {_short_name(u)}", f"acc:rm:{u.user_id}:l")] for u in groups[APPROVED]]
    rows += [[button(f"✅ Approve {_short_name(u)}", f"acc:ok:{u.user_id}:l")] for u in groups[DENIED]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != admin_id():
        await update.message.reply_text(ADMIN_ONLY)
        return
    text, markup = await users_view(get_services(context).db)
    await update.message.reply_text(text, reply_markup=markup)


async def decision_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != admin_id():
        await query.answer(ADMIN_ONLY, show_alert=True)
        return
    _, action, raw_id, where = query.data.split(":")
    user_id = int(raw_id)
    db = get_services(context).db
    target = await db.get_user(user_id)
    if not target:
        await query.answer("This person isn't on the list anymore.", show_alert=True)
        if where == "r":  # keep the old request as it was, minus buttons that no longer do anything
            await query.edit_message_reply_markup(None)
            return
    else:
        await query.answer()
        new_status = {"ok": APPROVED, "no": DENIED, "rm": None}[action]
        if new_status != target.status:
            if new_status:
                await db.set_user_status(user_id, new_status)
            else:
                await db.delete_user(user_id)
            await _tell(context, user_id, TELL_USER[new_status])
        if where == "r":
            await query.edit_message_text(
                f"🙋 <b>Access request</b>\n\n👤 {describe_user(user_id, target.username, target.full_name)}"
                f"\n\n{RESULT[new_status]}")
            return
    text, markup = await users_view(db)
    await query.edit_message_text(text, reply_markup=markup)


async def _tell(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str) -> None:
    try:
        await context.bot.send_message(user_id, text)
    except TelegramError:
        logger.info("Could not tell user %s about the access decision", user_id)


access_handlers = [
    CommandHandler("users", users_command),
    CallbackQueryHandler(decision_pressed, pattern=r"^acc:(ok|no|rm):\d+:[rl]$"),
]
