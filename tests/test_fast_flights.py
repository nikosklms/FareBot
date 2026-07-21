import pytest
from unittest.mock import patch, MagicMock
from providers.fast_flights import FastFlightsProvider
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_fast_flights_search_success():
    provider = FastFlightsProvider()
    mock_result = MagicMock()
    flight_item = MagicMock()
    flight_item.price = "€180"
    flight_item.name = "Aegean Airlines"
    mock_result.flights = [flight_item]

    with patch("providers.fast_flights.get_flights", return_value=mock_result):
        offers = await provider.search_flights(
            origin="ATH",
            destination="LON",
            departure_date="2026-08-15"
        )
        assert len(offers) == 1
        assert isinstance(offers[0], FlightOffer)
        assert offers[0].price == 180.0
        assert offers[0].origin == "ATH"
        assert offers[0].destination == "LON"
        assert offers[0].airline == "Aegean Airlines"
