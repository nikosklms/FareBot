import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_calendar_date_selection

@pytest.mark.asyncio
async def test_handle_track_dedup_prompt_on_duplicate():
    update = MagicMock()
    update.callback_query.data = "cal_day_2026-09-15"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"origin_code": "ATH", "destination_code": "MJT"}
    update.effective_user.id = 123

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.track.db_manager") as db_mock:
            db_mock.has_active_tracker = AsyncMock(return_value=True)
            await handle_calendar_date_selection(update, context)
            
            # Verify duplicate detection message and Update Existing Budget button
            msg = update.callback_query.message.reply_text.call_args[0][0]
            assert "Duplicate Tracker Detected" in msg
            reply_markup = update.callback_query.message.reply_text.call_args[1]["reply_markup"]
            button_labels = [b.text for row in reply_markup.inline_keyboard for b in row]
            assert any("Update Existing Budget" in label for label in button_labels)
