from functools import wraps
import inspect
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import ALLOWED_USERS

logger = logging.getLogger(__name__)

def restricted(func):
    """Decorator to restrict handler execution to user IDs listed in ALLOWED_USERS."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        user_id = user.id if user else None

        if user_id not in ALLOWED_USERS:
            logger.warning(f"Unauthorized access attempt by user_id={user_id}")
            if update.message and hasattr(update.message, "reply_text"):
                res = update.message.reply_text("⛔ **Access Denied**: You are not authorized to use this bot.")
                if inspect.isawaitable(res):
                    await res
            elif update.callback_query and hasattr(update.callback_query, "answer"):
                res = update.callback_query.answer("⛔ Access Denied: Unauthorized user", show_alert=True)
                if inspect.isawaitable(res):
                    await res
            return ConversationHandler.END

        return await func(update, context, *args, **kwargs)
    return wrapped
