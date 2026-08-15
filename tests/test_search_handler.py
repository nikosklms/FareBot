import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.search import execute_search, search_command, SEARCH_ORIGIN
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_execute_search_formatting():
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    mock_offer = FlightOffer(
        origin="ATH", destination="LON", departure_date="2026-08-15",
        price=190.0, airline="Aegean", booking_url="http://example.com"
    )

    with patch("bot.handlers.search.provider.search_flights", return_value=[mock_offer]):
        await execute_search(update, origin="ATH", destination="LON", date="2026-08-15")
        update.message.reply_text.assert_called()

@pytest.mark.asyncio
async def test_search_command_direct():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["ATH", "LON", "2026-08-15"]

    mock_offer = FlightOffer(
        origin="ATH", destination="LON", departure_date="2026-08-15",
        price=190.0, airline="Aegean", booking_url="http://example.com"
    )

    with patch("bot.handlers.search.provider.search_flights", return_value=[mock_offer]):
        res = await search_command(update, context)
        assert res == -1

@pytest.mark.asyncio
async def test_search_command_with_date_range():
    update = MagicMock()
    status_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_msg)
    context = MagicMock()
    context.args = ["ATH", "LON", "2026-09-01..2026-09-03"]

    mock_offer = FlightOffer(
        origin="ATH", destination="LON", departure_date="2026-09-02",
        price=90.0, airline="Aegean", booking_url="http://example.com"
    )

    with patch("bot.handlers.search.provider.search_flights_range", new_callable=AsyncMock) as mock_range:
        mock_range.return_value = [mock_offer]
        res = await search_command(update, context)
        assert res == -1
        mock_range.assert_called_once_with(
            origin="ATH", destination="LON", start_date="2026-09-01", end_date="2026-09-03", direct_only=False
        )

@pytest.mark.asyncio
async def test_search_command_wizard_start():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    res = await search_command(update, context)
    assert res == SEARCH_ORIGIN
    update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_search_wizard_flight_type_step():
    from bot.handlers.search import handle_search_date, select_search_flight_type_callback, SEARCH_FLIGHT_TYPE

    update = MagicMock()
    update.message.text = "2028-12-01"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {
        "search_origin_code": "ATH",
        "search_destination_code": "LON"
    }

    state = await handle_search_date(update, context)
    assert state == SEARCH_FLIGHT_TYPE
    assert context.user_data["search_departure_date"] == "2028-12-01"
    update.message.reply_text.assert_called_once()
    assert "type of flights" in update.message.reply_text.call_args[0][0].lower()


    # Test callback selection
    query = MagicMock()
    query.data = "src_fl_type_1"
    query.answer = AsyncMock()
    update.callback_query = query

    with patch("bot.handlers.search.execute_search", new=AsyncMock()) as mock_exec:
        next_state = await select_search_flight_type_callback(update, context)
        assert next_state == -1  # ConversationHandler.END
        mock_exec.assert_called_once_with(
            update, "ATH", "LON", "2028-12-01", direct_only=True
        )

@pytest.mark.asyncio
async def test_search_wizard_shows_cancel_button():
    """Search wizard prompt should include inline cancel button."""
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    await search_command(update, context)

    reply_markup = update.message.reply_text.call_args[1].get("reply_markup")
    assert reply_markup is not None
    cancel_btn = reply_markup.inline_keyboard[-1][0]
    assert cancel_btn.text == "❌ Cancel"
    assert cancel_btn.callback_data == "cancel_wizard"

@pytest.mark.asyncio
async def test_select_search_destination_callback_shows_date_presets():
    """Search wizard destination selection should render quick date preset buttons."""
    from bot.handlers.search import select_search_destination_callback
    update = MagicMock()
    query = MagicMock()
    query.data = "src_dst_LON_London"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    await select_search_destination_callback(update, context)

    assert query.message.edit_text.called
    kwargs = query.message.edit_text.call_args[1]
    reply_markup = kwargs.get("reply_markup")
    assert reply_markup is not None
    labels = [btn.text for row in reply_markup.inline_keyboard for btn in row]
    assert any("Next 7 Days" in label for label in labels)
    assert any("Next 14 Days" in label for label in labels)
    assert any("This Weekend" in label for label in labels)
    assert any("Custom Calendar" in label for label in labels)

@pytest.mark.asyncio
async def test_open_calendar_search_callback():
    from bot.handlers.search import open_calendar_search_callback, handle_search_calendar_date_selection, SEARCH_DATE, SEARCH_FLIGHT_TYPE
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.data = "open_cal_search"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await open_calendar_search_callback(update, context)
        assert state == SEARCH_DATE
        update.callback_query.message.edit_text.assert_called_once()

    update2 = MagicMock()
    update2.effective_user.id = 123
    update2.callback_query.data = "cal_day_2026-11-20"
    update2.callback_query.answer = AsyncMock()
    update2.callback_query.message.edit_text = AsyncMock()
    context2 = MagicMock()
    context2.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state2 = await handle_search_calendar_date_selection(update2, context2)
        assert state2 == SEARCH_FLIGHT_TYPE
        assert context2.user_data["search_departure_date"] == "2026-11-20"

@pytest.mark.asyncio
async def test_execute_search_departure_arrival_times_formatting():
    update = MagicMock()
    status_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_msg)

    offer = FlightOffer(
        "SKG", "ORY", "2027-04-03", price=85.0, airline="Transavia",
        is_direct=True, departure_time="17:45", arrival_time="19:55"
    )

    with patch("bot.handlers.search.provider.search_flights", return_value=[offer]):
        await execute_search(update, origin="SKG", destination="ORY", date="2027-04-03")
        status_msg.edit_text.assert_called_once()
        text = status_msg.edit_text.call_args[0][0]
        assert "17:45" in text
        assert "19:55" in text

@pytest.mark.asyncio
async def test_execute_search_overnight_day_offset_formatting():
    update = MagicMock()
    status_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_msg)

    offer = FlightOffer(
        "ATH", "LON", "2027-04-03", price=120.0, airline="Aegean",
        is_direct=True, departure_time="23:00", arrival_time="04:15", day_offset=1
    )

    with patch("bot.handlers.search.provider.search_flights", return_value=[offer]):
        await execute_search(update, origin="ATH", destination="LON", date="2027-04-03")
        status_msg.edit_text.assert_called_once()
        text = status_msg.edit_text.call_args[0][0]
        assert "23:00 ➔ 04:15 (+1)" in text

@pytest.mark.asyncio
async def test_execute_search_item_booking_url_hyperlink():
    update = MagicMock()
    status_msg = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_msg)

    offer = FlightOffer(
        "SKG", "ORY", "2027-04-03", price=85.0, airline="Transavia",
        is_direct=True, booking_url="https://www.google.com/travel/flights?q=test"
    )

    with patch("bot.handlers.search.provider.search_flights", return_value=[offer]):
        await execute_search(update, origin="SKG", destination="ORY", date="2027-04-03")
        status_msg.edit_text.assert_called_once()
        text = status_msg.edit_text.call_args[0][0]
        assert "[**€85.00**](https://www.google.com/travel/flights?q=test)" in text

@pytest.mark.asyncio
async def test_search_calendar_nav_mode_ignore():
    from bot.handlers.search import (
        search_calendar_nav_callback, search_calendar_mode_callback,
        search_calendar_ignore_callback, SEARCH_DATE
    )
    from bot.inline_calendar import create_calendar

    # 1. Test Navigation returns SEARCH_DATE and updates markup
    update = MagicMock()
    update.effective_user.id = 123
    update.callback_query.data = "cal_nav_2026-11"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.edit_reply_markup = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await search_calendar_nav_callback(update, context)
        assert state == SEARCH_DATE
        update.callback_query.message.edit_reply_markup.assert_called_once()

    # 2. Test Mode Toggle returns SEARCH_DATE and updates markup mode
    update_mode = MagicMock()
    update_mode.effective_user.id = 123
    update_mode.callback_query.data = "cal_mode_range"
    update_mode.callback_query.answer = AsyncMock()
    update_mode.callback_query.message.reply_markup = create_calendar(2026, 9, mode="single")
    update_mode.callback_query.message.edit_reply_markup = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_mode = await search_calendar_mode_callback(update_mode, context)
        assert state_mode == SEARCH_DATE
        update_mode.callback_query.message.edit_reply_markup.assert_called_once()
        new_markup = update_mode.callback_query.message.edit_reply_markup.call_args[1]["reply_markup"]
        button_datas = [b.callback_data for row in new_markup.inline_keyboard for b in row]
        assert any("cal_mode_single" in d for d in button_datas)

    # 3. Test Ignore returns SEARCH_DATE
    update_ignore = MagicMock()
    update_ignore.effective_user.id = 123
    update_ignore.callback_query.data = "cal_ignore"
    update_ignore.callback_query.answer = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state_ign = await search_calendar_ignore_callback(update_ignore, context)
        assert state_ign == SEARCH_DATE
        update_ignore.callback_query.answer.assert_called_once()

@pytest.mark.asyncio
async def test_search_calendar_range_selection_two_clicks():
    from bot.handlers.search import (
        search_calendar_mode_callback, handle_search_calendar_date_selection,
        SEARCH_DATE, SEARCH_FLIGHT_TYPE
    )

    # 1. Toggle to Range Mode
    update_mode = MagicMock()
    update_mode.effective_user.id = 123
    update_mode.callback_query.data = "cal_mode_range"
    update_mode.callback_query.answer = AsyncMock()
    update_mode.callback_query.message.edit_reply_markup = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state = await search_calendar_mode_callback(update_mode, context)
        assert state == SEARCH_DATE
        assert context.user_data.get("cal_mode") == "range"

    # 2. Click 1st date (Start Date: 2026-10-10)
    update_click1 = MagicMock()
    update_click1.effective_user.id = 123
    update_click1.callback_query.data = "cal_day_2026-10-10"
    update_click1.callback_query.answer = AsyncMock()
    update_click1.callback_query.message.edit_text = AsyncMock()
    update_click1.callback_query.message.edit_reply_markup = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state1 = await handle_search_calendar_date_selection(update_click1, context)
        assert state1 == SEARCH_DATE  # Stays in SEARCH_DATE awaiting end date
        assert context.user_data.get("cal_start_date") == "2026-10-10"

    # 3. Click 2nd date (End Date: 2026-10-15)
    update_click2 = MagicMock()
    update_click2.effective_user.id = 123
    update_click2.callback_query.data = "cal_day_2026-10-15"
    update_click2.callback_query.answer = AsyncMock()
    update_click2.callback_query.message.edit_text = AsyncMock()

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        state2 = await handle_search_calendar_date_selection(update_click2, context)
        assert state2 == SEARCH_FLIGHT_TYPE
        assert context.user_data["search_departure_date"] == "2026-10-10..2026-10-15"
        assert "cal_start_date" not in context.user_data









