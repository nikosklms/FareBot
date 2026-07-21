import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_origin_input, ORIGIN

@pytest.mark.asyncio
async def test_handle_origin_typo_resolution():
    update = MagicMock()
    update.message.text = "athen"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    next_state = await handle_origin_input(update, context)
    assert next_state == ORIGIN
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "ATH" in args[0] or "ATH" in str(kwargs.get("reply_markup", ""))
