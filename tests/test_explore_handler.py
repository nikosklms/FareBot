import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.explore import start_explore_wizard as explore_command, track_deal_callback

@pytest.mark.asyncio
async def test_track_deal_callback_success_and_dedup():
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.data = "track_deal_ATH_MJT_2026-09-15_36.0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        # Path 1: Non-duplicate -> Creates tracker with -10% budget rule (36.0 * 0.9 = 32.40) & updates markup to ✅ Tracked!
        with patch("bot.handlers.explore.db_manager") as db_mock:
            db_mock.has_active_tracker = AsyncMock(return_value=False)
            db_mock.get_active_trackers_count = AsyncMock(return_value=1)
            db_mock.create_tracker = AsyncMock(return_value=12)

            await track_deal_callback(update, context)
            db_mock.create_tracker.assert_called_once()
            assert abs(db_mock.create_tracker.call_args[1]["max_budget"] - 32.40) < 0.01

        # Path 2: Duplicate -> Answers with alert and updates button to Already Tracked
        with patch("bot.handlers.explore.db_manager") as db_mock:
            db_mock.get_active_trackers_count = AsyncMock(return_value=1)
            db_mock.has_active_tracker = AsyncMock(return_value=True)
            await track_deal_callback(update, context)
            update.callback_query.answer.assert_called_with("ℹ️ You are already tracking ATH → MJT on 2026-09-15!", show_alert=True)

@pytest.mark.asyncio
async def test_explore_timeframe_clears_stale_departure_date():
    from bot.handlers.explore import select_explore_timeframe_callback
    context = MagicMock()
    context.user_data = {"explore_departure_date": "2026-08-17..2026-10-16"}
    update = MagicMock()
    update.callback_query.data = "expl_tf_90"
    update.callback_query.answer = AsyncMock()
    
    with patch("bot.handlers.explore._ask_explore_limit") as ask_mock:
        ask_mock.return_value = 5
        await select_explore_timeframe_callback(update, context)
        assert "explore_departure_date" not in context.user_data
        assert context.user_data["explore_timeframe"] == 90

