import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.dashboard import mytracks_command, dashboard_callback_handler, handle_edit_budget_input

@pytest.mark.asyncio
async def test_mytracks_shows_edit_button_and_handles_edit():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

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
            assert context.user_data.get("edit_tracker_id") == 1

@pytest.mark.asyncio
async def test_handle_edit_budget_input_updates_db():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.text = "58"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"edit_tracker_id": 19}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.update_budget = AsyncMock()
            await handle_edit_budget_input(update, context)
            db_mock.update_budget.assert_called_once_with(19, 58.0)
            update.message.reply_text.assert_called_once()
            assert "€58.00" in update.message.reply_text.call_args[0][0]
            assert "edit_tracker_id" not in context.user_data

@pytest.mark.asyncio
async def test_dashboard_resume_digest_preserves_custom_schedule():
    update = MagicMock()
    update.callback_query.data = "dash_resume_101"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.effective_user.id = 123
    context = MagicMock()
    context.job_queue = MagicMock()

    digest_tracker_row = {
        "id": 101,
        "user_id": 123,
        "origin_code": "ATH",
        "destination_code": "REGION:EUROPE",
        "departure_date": "Friday@18:00",
        "max_budget": 80.0,
        "status": "PAUSED"
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_tracker_by_id = AsyncMock(return_value=digest_tracker_row)
            db_mock.update_tracker_status = AsyncMock()
            with patch("daemon.scheduler.schedule_digest_job") as sched_digest_mock:
                await dashboard_callback_handler(update, context)
                sched_digest_mock.assert_called_once_with(context.job_queue, 101, 123, "ATH", "europe", 80.0, "Friday@18:00")

@pytest.mark.asyncio
async def test_mytracks_displays_date_range_and_digest_horizon():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    range_tracker = {
        "id": 32, "status": "ACTIVE", "user_id": 123, "origin_code": "SKG",
        "destination_code": "LON", "departure_date": "2026-10-15", "departure_date_end": "2026-10-23",
        "max_budget": 300.0, "last_price_found": None, "direct_only": 1
    }
    digest_tracker = {
        "id": 30, "status": "ACTIVE", "user_id": 123, "origin_code": "SKG",
        "destination_code": "REGION:EUROPE", "departure_date": "30d|Sunday@15:00",
        "max_budget": 80.0, "last_price_found": None, "direct_only": 0
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.dashboard.db_manager") as db_mock:
            db_mock.get_user_trackers = AsyncMock(return_value=[range_tracker, digest_tracker])
            await mytracks_command(update, context)

            calls = update.message.reply_text.call_args_list
            assert len(calls) == 2
            range_text = calls[0][0][0]
            digest_text = calls[1][0][0]

            assert "2026-10-15 ➔ 2026-10-23" in range_text
            assert "30 Days Ahead" in digest_text
