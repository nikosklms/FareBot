import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_calendar_date_selection, handle_date_preset_callback, FLIGHT_TYPE

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

@pytest.mark.asyncio
async def test_handle_calendar_date_selection_success():
    update = MagicMock()
    update.callback_query.data = "cal_day_2026-10-15"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"origin_code": "SKG", "destination_code": "PVG"}
    update.effective_user.id = 123

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.track.db_manager") as db_mock:
            db_mock.has_active_tracker = AsyncMock(return_value=False)
            next_state = await handle_calendar_date_selection(update, context)
            assert next_state == FLIGHT_TYPE
            assert context.user_data["departure_date"] == "2026-10-15"
            update.callback_query.message.reply_text.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("preset_key", ["datepreset_next_7_days", "datepreset_next_14_days", "datepreset_this_weekend"])
async def test_handle_date_preset_callback_all_presets(preset_key):
    update = MagicMock()
    update.callback_query.data = preset_key
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    update.effective_user.id = 123

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        next_state = await handle_date_preset_callback(update, context)
        assert next_state == FLIGHT_TYPE
        assert "departure_date" in context.user_data
        assert "departure_date_end" in context.user_data
