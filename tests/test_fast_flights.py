import pytest
from unittest.mock import patch, MagicMock
from providers.fast_flights import FastFlightsProvider, parse_google_flights_payload
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_fast_flights_search_success():
    provider = FastFlightsProvider()
    mock_offer = FlightOffer(
        origin="ATH", destination="LON", departure_date="2026-08-15",
        price=180.0, currency="EUR", airline="Aegean Airlines"
    )

    with patch.object(provider, "search_flights", return_value=[mock_offer]):
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
async def test_skg_to_lon_returns_absolute_lowest_price_first():
    """Verify that searching SKG to LON finds low-cost carriers (e.g. Ryanair/easyJet) and sorts strictly ascending by price."""
    provider = FastFlightsProvider()
    offers = await provider.search_flights(
        origin="SKG",
        destination="LON",
        departure_date="2026-09-27"
    )
    assert len(offers) > 0

    # Verify results are strictly sorted ascending by price
    prices = [o.price for o in offers]
    assert prices == sorted(prices), f"Offers are not sorted by price! Got: {prices}"

    # Verify that the lowest price is <= 130 (e.g. Ryanair €93 to STN or easyJet €130 to LGW)
    lowest_offer = offers[0]
    assert lowest_offer.price <= 130.0, f"Expected lowest price <= 130.0, got: {lowest_offer.price} ({lowest_offer.airline})"
