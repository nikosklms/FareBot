import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.dashboard import mytracks_command, dashboard_callback_handler

@pytest.mark.asyncio
async def test_mytracks_shows_edit_button_and_handles_edit():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    mock_tracker = {
        "id": 1, "status": "ACTIVE", "user_id": 123, "origin_code": "ATH",
        "destination_code": "MJT", "departure_date": "2026-09-15",
        "max_budget": 50.0, "last_price_found": 36.0, "direct_only": 1
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_user_trackers = AsyncMock(return_value=[mock_tracker])
            await mytracks_command(update, context)
            
            reply_markup = update.message.reply_text.call_args[1]["reply_markup"]
            button_labels = [b.text for row in reply_markup.inline_keyboard for b in row]
            assert any("Edit" in label for label in button_labels)

        # Test callback for edit budget
        cb_update = MagicMock()
        cb_update.callback_query.data = "dash_editbudget_1"
        cb_update.callback_query.answer = AsyncMock()
        cb_update.callback_query.message.reply_text = AsyncMock()
        cb_update.effective_user.id = 123

        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_tracker_by_id = AsyncMock(return_value=mock_tracker)
            await dashboard_callback_handler(cb_update, context)
            cb_update.callback_query.message.reply_text.assert_called_once()
            assert "Send new target budget" in cb_update.callback_query.message.reply_text.call_args[0][0]
