import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.dashboard import mytracks_command

@pytest.mark.asyncio
async def test_mytracks_empty():
    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.dashboard.db_manager.get_user_trackers", return_value=[]):
        await mytracks_command(update, context)
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "no active or saved flight trackers" in text.lower()
