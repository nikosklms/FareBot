import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.search import execute_search
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
        # The second call is status_msg.edit_text on status_msg
