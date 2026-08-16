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
    update.callback_query.message.edit_text = AsyncMock()
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
            update.callback_query.message.edit_text.assert_called_once()

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

@pytest.mark.asyncio
async def test_track_calendar_nav_mode_ignore():
    from bot.handlers.track import (
        calendar_nav_callback, track_calendar_mode_callback,
        track_calendar_ignore_callback, DEPARTURE_DATE
    )
    from bot.inline_calendar import create_calendar

    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.data = "cal_nav_2026-11"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_reply_markup = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await calendar_nav_callback(update, context)
        assert state == DEPARTURE_DATE
        update.callback_query.message.edit_reply_markup.assert_called_once()

    update_mode = MagicMock()
    update_mode.effective_user.id = 123
    update_mode.callback_query.data = "cal_mode_range"
    update_mode.callback_query.answer = AsyncMock()
    update_mode.callback_query.message.reply_markup = create_calendar(2026, 9, mode="single")
    update_mode.callback_query.message.edit_reply_markup = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_mode = await track_calendar_mode_callback(update_mode, context)
        assert state_mode == DEPARTURE_DATE
        update_mode.callback_query.message.edit_reply_markup.assert_called_once()

    update_ignore = MagicMock()
    update_ignore.effective_user.id = 123
    update_ignore.callback_query.data = "cal_ignore"
    update_ignore.callback_query.answer = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_ign = await track_calendar_ignore_callback(update_ignore, context)
        assert state_ign == DEPARTURE_DATE
        update_ignore.callback_query.answer.assert_called_once()

@pytest.mark.asyncio
async def test_track_calendar_range_selection_two_clicks():
    from bot.handlers.track import (
        track_calendar_mode_callback, handle_calendar_date_selection,
        DEPARTURE_DATE, FLIGHT_TYPE
    )

    update_mode = MagicMock()
    update_mode.effective_user.id = 123
    update_mode.callback_query.data = "cal_mode_range"
    update_mode.callback_query.answer = AsyncMock()
    update_mode.callback_query.message.edit_reply_markup = AsyncMock()
    context = MagicMock()
    context.user_data = {"origin_code": "SKG", "destination_code": "PVG"}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await track_calendar_mode_callback(update_mode, context)
        assert state == DEPARTURE_DATE
        assert context.user_data.get("cal_mode") == "range"

    # Click 1: Start Date (2026-10-10)
    update_click1 = MagicMock()
    update_click1.effective_user.id = 123
    update_click1.callback_query.data = "cal_day_2026-10-10"
    update_click1.callback_query.answer = AsyncMock()
    update_click1.callback_query.message.edit_text = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state1 = await handle_calendar_date_selection(update_click1, context)
        assert state1 == DEPARTURE_DATE
        assert context.user_data.get("cal_start_date") == "2026-10-10"

    # Click 2: End Date (2026-10-15)
    update_click2 = MagicMock()
    update_click2.effective_user.id = 123
    update_click2.callback_query.data = "cal_day_2026-10-15"
    update_click2.callback_query.answer = AsyncMock()
    update_click2.callback_query.message.edit_text = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.track.db_manager") as db_mock:
            db_mock.has_active_tracker = AsyncMock(return_value=False)
            state2 = await handle_calendar_date_selection(update_click2, context)
            assert state2 == FLIGHT_TYPE
            assert context.user_data["departure_date"] == "2026-10-10"
            assert context.user_data["departure_date_end"] == "2026-10-15"


