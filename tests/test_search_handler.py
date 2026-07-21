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
    assert "flight type preference" in update.message.reply_text.call_args[0][0].lower()


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




