import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_origin_input, ORIGIN

@pytest.mark.asyncio
async def test_handle_origin_typo_resolution():
    update = MagicMock()
    update.message.text = "athen"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    next_state = await handle_origin_input(update, context)
    assert next_state == ORIGIN
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "ATH" in args[0] or "ATH" in str(kwargs.get("reply_markup", ""))

@pytest.mark.asyncio
async def test_handle_departure_date_validation():
    from bot.handlers.track import handle_departure_date, DEPARTURE_DATE, BUDGET

    update = MagicMock()
    update.message.text = "invalid-date"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    # Invalid format should stay in DEPARTURE_DATE
    state = await handle_departure_date(update, context)
    assert state == DEPARTURE_DATE
    assert "Invalid date format" in update.message.reply_text.call_args[0][0]

    # Past date should stay in DEPARTURE_DATE
    update.message.text = "2000-01-01"
    state = await handle_departure_date(update, context)
    assert state == DEPARTURE_DATE
    assert "cannot be in the past" in update.message.reply_text.call_args[0][0]

    # Future date should advance to FLIGHT_TYPE state
    update.message.text = "2028-12-01"
    state = await handle_departure_date(update, context)
    assert context.user_data["departure_date"] == "2028-12-01"

@pytest.mark.asyncio
async def test_handle_flight_type_selection():
    from bot.handlers.track import select_flight_type_callback, BUDGET

    update = MagicMock()
    query = MagicMock()
    query.data = "fl_type_1"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_flight_type_callback(update, context)
    assert state == BUDGET
    assert context.user_data["direct_only"] == 1

@pytest.mark.asyncio
async def test_handle_budget_validation():
    from bot.handlers.track import handle_budget, BUDGET, FREQUENCY

    update = MagicMock()
    update.message.text = "-50"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    # Negative budget should stay in BUDGET
    state = await handle_budget(update, context)
    assert state == BUDGET

    # Non-numeric budget should stay in BUDGET
    update.message.text = "abc"
    state = await handle_budget(update, context)
    assert state == BUDGET

    # Valid positive budget should advance to FREQUENCY
    update.message.text = "150.50"
    state = await handle_budget(update, context)
    assert state == FREQUENCY
    assert context.user_data["max_budget"] == 150.50


