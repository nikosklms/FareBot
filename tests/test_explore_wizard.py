import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.ext import ConversationHandler
from bot.handlers.explore import (
    start_explore_wizard,
    handle_explore_origin_input,
    select_explore_origin_callback,
    select_explore_region_callback,
    select_explore_sort_callback,
    select_explore_timeframe_callback,
    select_explore_budget_callback,
    select_explore_limit_callback,
    EXPLORE_ORIGIN,
    EXPLORE_REGION,
    EXPLORE_SORT,
    EXPLORE_TIMEFRAME,
    EXPLORE_BUDGET,
    EXPLORE_LIMIT
)

@pytest.mark.asyncio
async def test_explore_wizard_one_line_shortcut():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["ATH", "europe", "30", "100", "5"]

    mock_deals = [
        {
            "origin_code": "ATH",
            "destination_code": "FCO",
            "destination_name": "Rome Fiumicino",
            "price": 80.0,
            "airline": "Aegean",
            "departure_date": "2026-09-15",
            "discount_pct": 20.0
        }
    ]

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.explore.run_explore_query", AsyncMock(return_value=mock_deals)):
            res = await start_explore_wizard(update, context)
            assert res == ConversationHandler.END

@pytest.mark.asyncio
async def test_explore_wizard_step_by_step_flow():
    # Step 1: /explore start -> prompts origin selection
    update1 = MagicMock()
    update1.effective_user.id = 123
    update1.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state1 = await start_explore_wizard(update1, context)
        assert state1 == EXPLORE_ORIGIN

    # Select Origin ATH -> prompts Region selection
    query2 = MagicMock()
    query2.data = "expl_org_ATH_Athens"
    query2.answer = AsyncMock()
    query2.message.edit_text = AsyncMock()
    update2 = MagicMock()
    update2.effective_user.id = 123
    update2.callback_query = query2

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state2 = await select_explore_origin_callback(update2, context)
        assert state2 == EXPLORE_REGION
        assert context.user_data["explore_origin"] == "ATH"

    # Select Region Europe -> prompts Sort mode selection
    query3 = MagicMock()
    query3.data = "expl_reg_europe"
    query3.answer = AsyncMock()
    query3.message.edit_text = AsyncMock()
    update3 = MagicMock()
    update3.effective_user.id = 123
    update3.callback_query = query3

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state3 = await select_explore_region_callback(update3, context)
        assert state3 == EXPLORE_SORT
        assert context.user_data["explore_region"] == "europe"

    # Select Sort Mode 'both' -> prompts Timeframe selection
    from bot.handlers.explore import select_explore_sort_callback
    query_sort = MagicMock()
    query_sort.data = "expl_sort_both"
    query_sort.answer = AsyncMock()
    query_sort.message.edit_text = AsyncMock()
    update_sort = MagicMock()
    update_sort.effective_user.id = 123
    update_sort.callback_query = query_sort

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_sort = await select_explore_sort_callback(update_sort, context)
        assert state_sort == EXPLORE_TIMEFRAME
        assert context.user_data["explore_sort"] == "both"

    # Select Timeframe 30d -> prompts Budget selection
    query4 = MagicMock()
    query4.data = "expl_tf_30"
    query4.answer = AsyncMock()
    query4.message.edit_text = AsyncMock()
    update4 = MagicMock()
    update4.effective_user.id = 123
    update4.callback_query = query4

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state4 = await select_explore_timeframe_callback(update4, context)
        assert state4 == EXPLORE_BUDGET
        assert context.user_data["explore_timeframe"] == 30

    # Select Budget 100 EUR -> prompts Limit selection
    query5 = MagicMock()
    query5.data = "expl_bud_100"
    query5.answer = AsyncMock()
    query5.message.edit_text = AsyncMock()
    update5 = MagicMock()
    update5.effective_user.id = 123
    update5.callback_query = query5

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state5 = await select_explore_budget_callback(update5, context)
        assert state5 == EXPLORE_LIMIT
        assert context.user_data["explore_budget"] == 100.0

    # Select Limit 10 -> executes query and returns ConversationHandler.END
    query6 = MagicMock()
    query6.data = "expl_lim_10"
    query6.answer = AsyncMock()
    query6.message.edit_text = AsyncMock()
    query6.message.reply_text = AsyncMock()
    update6 = MagicMock()
    update6.effective_user.id = 123
    update6.callback_query = query6

    mock_deals = [
        {
            "origin_code": "ATH",
            "destination_code": "FCO",
            "destination_name": "Rome Fiumicino",
            "price": 80.0,
            "airline": "Aegean",
            "departure_date": "2026-09-15",
            "discount_pct": 20.0
        }
    ]

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.explore.run_explore_query", AsyncMock(return_value=mock_deals)):
            state6 = await select_explore_limit_callback(update6, context)
            assert state6 == ConversationHandler.END

@pytest.mark.asyncio
async def test_explore_calendar_callbacks():
    from bot.handlers.explore import (
        open_calendar_explore_callback, explore_calendar_nav_callback,
        explore_calendar_mode_callback, explore_calendar_ignore_callback,
        handle_explore_calendar_date_selection, EXPLORE_TIMEFRAME, EXPLORE_BUDGET
    )
    from bot.inline_calendar import create_calendar

    # 1. Open Calendar
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await open_calendar_explore_callback(update, context)
        assert state == EXPLORE_TIMEFRAME
        update.callback_query.message.edit_text.assert_called_once()

    # 2. Navigation
    update_nav = MagicMock()
    update_nav.effective_user.id = 123
    update_nav.callback_query.data = "cal_nav_2026-11"
    update_nav.callback_query.answer = AsyncMock()
    update_nav.callback_query.message.edit_reply_markup = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_nav = await explore_calendar_nav_callback(update_nav, context)
        assert state_nav == EXPLORE_TIMEFRAME

    # 3. Single Date Selection
    update_day = MagicMock()
    update_day.effective_user.id = 123
    update_day.callback_query.data = "cal_day_2026-10-15"
    update_day.callback_query.answer = AsyncMock()
    update_day.callback_query.message.edit_text = AsyncMock()
    context_day = MagicMock()
    context_day.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_day = await handle_explore_calendar_date_selection(update_day, context_day)
        assert state_day == EXPLORE_BUDGET
        assert context_day.user_data["explore_departure_date"] == "2026-10-15"

@pytest.mark.asyncio
async def test_explore_calendar_range_selection():
    from bot.handlers.explore import (
        explore_calendar_mode_callback, handle_explore_calendar_date_selection,
        EXPLORE_TIMEFRAME, EXPLORE_BUDGET
    )

    update_mode = MagicMock()
    update_mode.effective_user.id = 123
    update_mode.callback_query.data = "cal_mode_range"
    update_mode.callback_query.answer = AsyncMock()
    update_mode.callback_query.message.edit_reply_markup = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await explore_calendar_mode_callback(update_mode, context)
        assert state == EXPLORE_TIMEFRAME
        assert context.user_data.get("cal_mode") == "range"

    # Click 1: Start Date (2026-10-10)
    update_click1 = MagicMock()
    update_click1.effective_user.id = 123
    update_click1.callback_query.data = "cal_day_2026-10-10"
    update_click1.callback_query.answer = AsyncMock()
    update_click1.callback_query.message.edit_text = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state1 = await handle_explore_calendar_date_selection(update_click1, context)
        assert state1 == EXPLORE_TIMEFRAME
        assert context.user_data.get("cal_start_date") == "2026-10-10"

    # Click 2: End Date (2026-10-20)
    update_click2 = MagicMock()
    update_click2.effective_user.id = 123
    update_click2.callback_query.data = "cal_day_2026-10-20"
    update_click2.callback_query.answer = AsyncMock()
    update_click2.callback_query.message.edit_text = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state2 = await handle_explore_calendar_date_selection(update_click2, context)
        assert state2 == EXPLORE_BUDGET
        assert context.user_data["explore_departure_date"] == "2026-10-10..2026-10-20"

