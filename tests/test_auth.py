import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.ext import ConversationHandler
from bot.handlers.auth import restricted

@pytest.mark.asyncio
async def test_restricted_decorator_allows_authorized_user():
    """Authorized user in ALLOWED_USERS should be allowed to execute handler."""
    dummy_handler = AsyncMock(return_value="success")
    decorated = restricted(dummy_handler)

    update = MagicMock()
    update.effective_user.id = 123456789
    context = MagicMock()

    result = await decorated(update, context)

    assert result == "success"
    dummy_handler.assert_called_once_with(update, context)


@pytest.mark.asyncio
async def test_restricted_decorator_blocks_unauthorized_user_message():
    """Unauthorized user sending a message should receive Access Denied and ConversationHandler.END."""
    dummy_handler = AsyncMock(return_value="should_not_be_called")
    decorated = restricted(dummy_handler)

    update = MagicMock()
    update.effective_user.id = 99999999  # Unauthorized ID
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    context = MagicMock()

    result = await decorated(update, context)

    assert result == ConversationHandler.END
    dummy_handler.assert_not_called()
    update.message.reply_text.assert_called_once()
    assert "Access Denied" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_restricted_decorator_blocks_unauthorized_user_callback():
    """Unauthorized user triggering a callback query should get an alert answer and ConversationHandler.END."""
    dummy_handler = AsyncMock(return_value="should_not_be_called")
    decorated = restricted(dummy_handler)

    update = MagicMock()
    update.effective_user.id = 99999999  # Unauthorized ID
    update.message = None
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    context = MagicMock()

    result = await decorated(update, context)

    assert result == ConversationHandler.END
    dummy_handler.assert_not_called()
    update.callback_query.answer.assert_called_once_with("⛔ Access Denied: Unauthorized user", show_alert=True)
