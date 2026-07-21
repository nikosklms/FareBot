import pytest
from unittest.mock import patch, MagicMock
from providers.fast_flights import FastFlightsProvider
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_fast_flights_search_success():
    provider = FastFlightsProvider()
    mock_item = MagicMock()
    mock_item.price = 180.0
    mock_item.airlines = ["Aegean Airlines"]

    with patch("providers.fast_flights.get_flights", return_value=[mock_item]):
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

@pytest.mark.asyncio
async def test_reproduce_skg_to_lon_live():
    """Live integration test for SKG to LON search."""
    provider = FastFlightsProvider()
    offers = await provider.search_flights(
        origin="SKG",
        destination="LON",
        departure_date="2026-09-27"
    )
    assert len(offers) > 0
    assert offers[0].origin == "SKG"
    assert offers[0].destination == "LON"
    assert offers[0].price > 0
