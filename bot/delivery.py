"""How a finished search reaches the user.

Telegram notifies for new messages but not for edits, so editing the progress message into the
results let a long search or a digest finish silently. The outcome is sent as new messages and
the progress message is deleted instead.
"""
import logging
from typing import Optional

from telegram import Bot, InlineKeyboardMarkup, Message
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


async def deliver(bot: Bot, chat_id: int, status: Optional[Message], chunks: list[str],
                  reply_markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
    """Send the chunks (the keyboard goes on the last one), then delete the progress message.

    Returns the last message sent, or None if sending failed; the progress message then stays.
    """
    last = None
    for index, chunk in enumerate(chunks):
        try:
            last = await bot.send_message(chat_id=chat_id, text=chunk,
                                          reply_markup=reply_markup if index == len(chunks) - 1 else None)
        except TelegramError:
            logger.exception("Failed to send search results to %s", chat_id)
            return None
    if status:
        try:
            await status.delete()
        except TelegramError:
            logger.debug("Could not delete the progress message", exc_info=True)  # harmless leftover
    return last
