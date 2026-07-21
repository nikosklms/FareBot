import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.handlers.common import start_command, help_command, cancel_command

@pytest.mark.asyncio
async def test_start_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await start_command(update, context)
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Fare Bot" in text

@pytest.mark.asyncio
async def test_help_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await help_command(update, context)
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Guide" in text or "Instant Search" in text

@pytest.mark.asyncio
async def test_cancel_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    res = await cancel_command(update, context)
    assert res == -1  # ConversationHandler.END is -1
    update.message.reply_text.assert_called_once()
