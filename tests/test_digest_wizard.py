import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.ext import ConversationHandler
from bot.handlers.digest import (
    start_digest_wizard,
    select_digest_origin_callback,
    select_digest_region_callback,
    select_digest_sort_callback,
    select_digest_budget_callback,
    select_digest_timeframe_callback,
    select_digest_day_callback,
    select_digest_time_callback,
    select_digest_limit_callback,
    DIGEST_ORIGIN,
    DIGEST_REGION,
    DIGEST_SORT,
    DIGEST_BUDGET,
    DIGEST_TIMEFRAME,
    DIGEST_DAY,
    DIGEST_TIME,
    DIGEST_LIMIT
)
from daemon.scheduler import calculate_next_digest_delay, run_digest_weekly_job

def test_calculate_next_digest_delay():
    # Test day/time calculation for next Sunday@15:00 or 30d|Sunday@15:00 or 30d|price|Sunday@15:00
    delay = calculate_next_digest_delay("30d|Sunday@15:00")
    assert delay > 0 and delay <= 7 * 86400

    delay_3part = calculate_next_digest_delay("30d|price|Saturday@16:25")
    assert delay_3part > 0 and delay_3part <= 7 * 86400

@pytest.mark.asyncio
async def test_digest_wizard_full_step_by_step_flow():
    # Step 1: /digest start -> prompts origin selection
    update1 = MagicMock()
    update1.effective_user.id = 123
    update1.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state1 = await start_digest_wizard(update1, context)
        assert state1 == DIGEST_ORIGIN

    # Select Origin ATH -> prompts Region
    query2 = MagicMock()
    query2.data = "dig_org_ATH_Athens"
    query2.answer = AsyncMock()
    query2.message.edit_text = AsyncMock()
    update2 = MagicMock()
    update2.effective_user.id = 123
    update2.callback_query = query2

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state2 = await select_digest_origin_callback(update2, context)
        assert state2 == DIGEST_REGION
        assert context.user_data["digest_origin"] == "ATH"

    # Select Region Europe -> prompts Sort
    query3 = MagicMock()
    query3.data = "dig_reg_europe"
    query3.answer = AsyncMock()
    query3.message.edit_text = AsyncMock()
    update3 = MagicMock()
    update3.effective_user.id = 123
    update3.callback_query = query3

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state3 = await select_digest_region_callback(update3, context)
        assert state3 == DIGEST_SORT
        assert context.user_data["digest_region"] == "europe"

    # Select Sort Price -> prompts Budget
    query_sort = MagicMock()
    query_sort.data = "dig_sort_price"
    query_sort.answer = AsyncMock()
    query_sort.message.edit_text = AsyncMock()
    update_sort = MagicMock()
    update_sort.effective_user.id = 123
    update_sort.callback_query = query_sort

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_sort = await select_digest_sort_callback(update_sort, context)
        assert state_sort == DIGEST_BUDGET
        assert context.user_data["digest_sort"] == "price"

    # Select Budget 80 -> prompts Timeframe
    query4 = MagicMock()
    query4.data = "dig_bud_80"
    query4.answer = AsyncMock()
    query4.message.edit_text = AsyncMock()
    update4 = MagicMock()
    update4.effective_user.id = 123
    update4.callback_query = query4

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state4 = await select_digest_budget_callback(update4, context)
        assert state4 == DIGEST_TIMEFRAME
        assert context.user_data["digest_budget"] == 80.0

    # Select Timeframe 30 -> prompts Day
    query5 = MagicMock()
    query5.data = "dig_tf_30"
    query5.answer = AsyncMock()
    query5.message.edit_text = AsyncMock()
    update5 = MagicMock()
    update5.effective_user.id = 123
    update5.callback_query = query5

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state5 = await select_digest_timeframe_callback(update5, context)
        assert state5 == DIGEST_DAY
        assert context.user_data["digest_timeframe"] == 30

    # Select Day Sunday -> prompts Time
    query6 = MagicMock()
    query6.data = "dig_day_Sunday"
    query6.answer = AsyncMock()
    query6.message.edit_text = AsyncMock()
    update6 = MagicMock()
    update6.effective_user.id = 123
    update6.callback_query = query6

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state6 = await select_digest_day_callback(update6, context)
        assert state6 == DIGEST_TIME
        assert context.user_data["digest_day"] == "Sunday"

    # Select Time 15:00 -> prompts Limit
    query7 = MagicMock()
    query7.data = "dig_time_15:00"
    query7.answer = AsyncMock()
    query7.message.edit_text = AsyncMock()
    update7 = MagicMock()
    update7.effective_user.id = 123
    update7.callback_query = query7

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state7 = await select_digest_time_callback(update7, context)
        assert state7 == DIGEST_LIMIT
        assert context.user_data["digest_time"] == "15:00"

    # Select Limit 10 -> saves tracker, schedules job, finishes wizard
    query8 = MagicMock()
    query8.data = "dig_lim_10"
    query8.answer = AsyncMock()
    query8.message.edit_text = AsyncMock()
    update8 = MagicMock()
    update8.effective_user.id = 123
    update8.callback_query = query8

    context.job_queue = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.digest.db_manager") as db_mock:
            db_mock.has_active_digest = AsyncMock(return_value=False)
            db_mock.create_tracker = AsyncMock(return_value=77)

            with patch("bot.handlers.digest.schedule_digest_job") as sched_mock:
                state8 = await select_digest_limit_callback(update8, context)
                assert state8 == ConversationHandler.END
                db_mock.create_tracker.assert_called_once()
                kw = db_mock.create_tracker.call_args[1]
                assert kw["departure_date"] == "30d|price|Sunday@15:00"
                sched_mock.assert_called_once()

@pytest.mark.asyncio
async def test_digest_wizard_stores_custom_schedule_str():
    query = MagicMock()
    query.data = "dig_lim_10"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query = query
    context = MagicMock()
    context.job_queue = MagicMock()
    context.user_data = {
        "digest_origin": "ATH",
        "digest_region": "europe",
        "digest_sort": "discount",
        "digest_timeframe": 60,
        "digest_day": "Friday",
        "digest_time": "18:00"
    }

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.digest.db_manager") as db_mock:
            db_mock.has_active_digest = AsyncMock(return_value=False)
            db_mock.create_tracker = AsyncMock(return_value=88)
            with patch("bot.handlers.digest.schedule_digest_job") as sched_mock:
                await select_digest_limit_callback(update, context)
                db_mock.create_tracker.assert_called_once()
                kw = db_mock.create_tracker.call_args[1]
                assert kw["departure_date"] == "60d|discount|Friday@18:00"

@pytest.mark.asyncio
async def test_digest_wizard_calendar_callbacks():
    from bot.handlers.digest import open_calendar_digest_callback, handle_digest_calendar_date_selection, DIGEST_TIMEFRAME
    query = MagicMock()
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await open_calendar_digest_callback(update, context)
        assert state == DIGEST_TIMEFRAME
        assert context.user_data["cal_mode"] == "range"

        query.data = "cal_day_2026-10-15"
        state2 = await handle_digest_calendar_date_selection(update, context)
        assert state2 == DIGEST_TIMEFRAME
        assert context.user_data["cal_start_date"] == "2026-10-15"

