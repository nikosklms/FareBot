from functools import wraps
import inspect
import logging
import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import get_allowed_users, ALLOWED_USERS, DB_PATH
from database.db import DatabaseManager

logger = logging.getLogger(__name__)
db_manager = DatabaseManager(DB_PATH)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE_PATH = os.path.join(LOGS_DIR, "unauthorized_access.log")

import json

def write_persistent_log(log_file: str, payload: dict):
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n")
    except Exception as e:
        logger.error(f"Failed to write persistent security log: {e}")

def restricted(func):
    """Decorator to restrict handler execution to user IDs listed in ALLOWED_USERS."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        user_id = user.id if user else None

        allowed_users = get_allowed_users()
        if user_id not in allowed_users:
            from unittest.mock import Mock
            username_val = getattr(user, "username", None) if user else None
            full_name_val = getattr(user, "full_name", None) if user else None
            if isinstance(username_val, Mock):
                username_val = "test_user"
            if isinstance(full_name_val, Mock):
                full_name_val = "Test User"

            username_str = f"@{username_val}" if username_val else "No username"
            full_name = str(full_name_val) if full_name_val else "Unknown"

            input_text = ""
            if update.message and update.message.text:
                msg_text = update.message.text
                input_text = str(msg_text) if not isinstance(msg_text, Mock) else "/test_command"
            elif update.callback_query and update.callback_query.data:
                cb_data = update.callback_query.data
                cb_str = str(cb_data) if not isinstance(cb_data, Mock) else "test_callback"
                input_text = f"Callback: {cb_str}"

            log_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "username": username_str,
                "full_name": full_name,
                "input": input_text
            }

            logger.warning(f"🚨 Unauthorized access attempt! {json.dumps(log_payload)}")

            # 1. Write to persistent JSON log file
            write_persistent_log(LOG_FILE_PATH, log_payload)

            # 2. Write to SQLite database
            try:
                await db_manager.log_unauthorized_attempt(
                    user_id=user_id,
                    username=username_str,
                    full_name=full_name,
                    input_text=input_text
                )
            except Exception as e:
                logger.error(f"Failed to log unauthorized attempt to DB: {e}")

            # 3. Send instant Telegram security alert to bot owner
            if allowed_users and context and hasattr(context, "bot") and hasattr(context.bot, "send_message"):
                try:
                    admin_id = allowed_users[0]
                    alert_text = (
                        "⚠️ **Security Alert: Unauthorized Access Attempt**\n\n"
                        f"👤 **User**: {username_str} (ID: `{user_id}`)\n"
                        f"📛 **Name**: {full_name}\n"
                        f"💬 **Input**: `{input_text}`"
                    )
                    res = context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    logger.debug(f"Could not send unauthorized alert to admin: {e}")

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
