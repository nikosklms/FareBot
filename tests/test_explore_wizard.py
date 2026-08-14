import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.ext import ConversationHandler
from bot.handlers.explore import (
    start_explore_wizard,
    handle_explore_origin_input,
    select_explore_origin_callback,
    select_explore_region_callback,
    select_explore_budget_callback,
    select_explore_limit_callback,
    EXPLORE_ORIGIN,
    EXPLORE_REGION,
    EXPLORE_BUDGET,
    EXPLORE_LIMIT
)

@pytest.mark.asyncio
async def test_explore_wizard_one_line_shortcut():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["ATH", "europe", "100", "5"]

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

    # Select Region Europe -> prompts Budget selection
    query3 = MagicMock()
    query3.data = "expl_reg_europe"
    query3.answer = AsyncMock()
    query3.message.edit_text = AsyncMock()
    update3 = MagicMock()
    update3.effective_user.id = 123
    update3.callback_query = query3

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state3 = await select_explore_region_callback(update3, context)
        assert state3 == EXPLORE_BUDGET
        assert context.user_data["explore_region"] == "europe"

    # Select Budget 100 EUR -> prompts Limit selection
    query4 = MagicMock()
    query4.data = "expl_bud_100"
    query4.answer = AsyncMock()
    query4.message.edit_text = AsyncMock()
    update4 = MagicMock()
    update4.effective_user.id = 123
    update4.callback_query = query4

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state4 = await select_explore_budget_callback(update4, context)
        assert state4 == EXPLORE_LIMIT
        assert context.user_data["explore_budget"] == 100.0

    # Select Limit 10 -> executes query and returns ConversationHandler.END
    query5 = MagicMock()
    query5.data = "expl_lim_10"
    query5.answer = AsyncMock()
    query5.message.edit_text = AsyncMock()
    query5.message.reply_text = AsyncMock()
    update5 = MagicMock()
    update5.effective_user.id = 123
    update5.callback_query = query5

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
            state5 = await select_explore_limit_callback(update5, context)
            assert state5 == ConversationHandler.END
