import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.explore import explore_command, track_deal_callback

@pytest.mark.asyncio
async def test_track_deal_callback_success_and_dedup():
    update = MagicMock()
    update.callback_query.data = "track_deal_ATH_MJT_2026-09-15_36.0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    context = MagicMock()

    # Path 1: Non-duplicate -> Creates tracker with -10% budget rule (36.0 * 0.9 = 32.40) & updates markup to ✅ Tracked!
    with patch("bot.handlers.explore.db_manager") as db_mock:
        db_mock.has_active_tracker = AsyncMock(return_value=False)
        db_mock.get_active_trackers_count = AsyncMock(return_value=1)
        db_mock.create_tracker = AsyncMock(return_value=12)

        await track_deal_callback(update, context)
        db_mock.create_tracker.assert_called_once()
        assert abs(db_mock.create_tracker.call_args[1]["max_budget"] - 32.40) < 0.01
        update.callback_query.edit_message_reply_markup.assert_called_once()

    # Path 2: Duplicate -> Answers with alert and updates button to Already Tracked
    with patch("bot.handlers.explore.db_manager") as db_mock:
        db_mock.has_active_tracker = AsyncMock(return_value=True)
        await track_deal_callback(update, context)
        update.callback_query.answer.assert_called_with("⚠️ You are already tracking ATH → MJT for 2026-09-15!", show_alert=True)
