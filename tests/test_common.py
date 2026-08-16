import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.ext import ConversationHandler
from bot.handlers.common import cancel_callback

@pytest.mark.asyncio
async def test_cancel_callback_edits_message():
    update = MagicMock()
    query = MagicMock()
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()

    res = await cancel_callback(update, context)

    assert res == ConversationHandler.END
    query.answer.assert_called_once()
    query.message.edit_text.assert_called_once_with("❌ Action cancelled.")

def test_build_status_estimate_text_includes_clock_for_seconds():
    from bot.handlers.common import build_status_estimate_text
    text = build_status_estimate_text("Header", est_seconds=30.0, total_queries=5)
    assert "around" in text
    assert "secs" in text

