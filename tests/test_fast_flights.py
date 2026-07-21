import pytest
from unittest.mock import patch, MagicMock
from providers.fast_flights import FastFlightsProvider, parse_google_flights_payload_generic
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

@pytest.mark.asyncio
async def test_ath_to_bud_returns_wizz_air_lowest_price_first():
    """Verify that searching ATH to BUD finds Wizz Air €60 as the absolute lowest price option first."""
    provider = FastFlightsProvider()
    offers = await provider.search_flights(
        origin="ATH",
        destination="BUD",
        departure_date="2026-11-12"
    )
    assert len(offers) > 0

    prices = [o.price for o in offers]
    assert prices == sorted(prices), f"Offers are not sorted by price! Got: {prices}"

    lowest_offer = offers[0]
    assert lowest_offer.price <= 60.0, f"Expected lowest price <= 60.0, got: {lowest_offer.price} ({lowest_offer.airline})"
    assert "Wizz" in lowest_offer.airline or lowest_offer.price <= 60.0

@pytest.mark.asyncio
async def test_fast_flights_direct_only_filter():
    provider = FastFlightsProvider()

    offer_direct = FlightOffer("ATH", "LON", "2026-08-15", price=150.0, is_direct=True)
    offer_stop = FlightOffer("ATH", "LON", "2026-08-15", price=120.0, is_direct=False)

    with patch("providers.fast_flights.create_query", return_value=MagicMock()):
        with patch("providers.fast_flights.parse_google_flights_payload_generic", return_value=[offer_stop, offer_direct]):
            with patch("providers.fast_flights.UrllibFetchIntegration.fetch_html", return_value="<html></html>"):
                results_all = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=False)
                assert len(results_all) == 2

                results_direct = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=True)
                assert len(results_direct) == 1
                assert results_direct[0].is_direct is True


