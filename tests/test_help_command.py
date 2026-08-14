import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.common import help_command, start_command

@pytest.mark.asyncio
async def test_help_and_start_commands_include_new_features():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        # Test help_command
        await help_command(update, context)
        help_text = update.message.reply_text.call_args[0][0]
        assert "/explore" in help_text
        assert "/digest" in help_text
        assert "up to 20 max" in help_text or "20 max" in help_text

        # Test start_command
        update.message.reply_text.reset_mock()
        await start_command(update, context)
        start_text = update.message.reply_text.call_args[0][0]
        assert "/explore" in start_text
        assert "/digest" in start_text
