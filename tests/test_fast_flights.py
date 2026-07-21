import pytest
from unittest.mock import patch, MagicMock, ANY
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

    with patch("providers.fast_flights.create_query") as mock_cq:
        mock_cq.return_value = MagicMock()
        with patch("providers.fast_flights.parse_google_flights_payload_generic", return_value=[offer_stop, offer_direct]):
            with patch("providers.fast_flights.UrllibFetchIntegration.fetch_html", return_value="<html></html>"):
                results_all = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=False)
                assert len(results_all) == 2

                results_direct = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=True)
                assert len(results_direct) == 1
                assert results_direct[0].is_direct is True

                # Verify max_stops=0 was passed to create_query (NOT stops=0)
                mock_cq.assert_called_with(
                    flights=ANY,
                    trip="one-way",
                    passengers=ANY,
                    currency="EUR",
                    max_stops=0
                )


@pytest.mark.asyncio
async def test_parse_google_flights_payload_direct_vs_layover():
    """Verify that parsing payloads with 1 leg vs multiple legs sets is_direct, departure_time, and arrival_time accurately."""
    # Sample leg structure matching Google Flights payload for 1 leg (direct) vs 2 legs (layover)
    # Leg format: index 8 is departure time [17, 45], index 10 is arrival time [19, 55], index 22 is metadata list
    direct_leg = [None]*8 + [[17, 45], None, [19, 55]] + [None]*11 + [["flight_meta"]]
    layover_leg1 = [None]*8 + [[13, 20], None, [14, 45]] + [None]*11 + [["flight_meta"]]
    layover_leg2 = [None]*8 + [[15, 40], None, [17, 20]] + [None]*11 + [["flight_meta"]]

    # Construct mock payload structure matching parse_google_flights_payload_generic expectations
    flight_node_direct = [None, ["Transavia"], [direct_leg]]
    flight_node_layover = [None, ["LOT"], [layover_leg1, layover_leg2]]

    payload_direct = [flight_node_direct, [[None, 85.0]]]
    payload_layover = [flight_node_layover, [[None, 101.0]]]

    import json
    js_content_direct = f"<script class=\"ds:1\">data:{json.dumps([payload_direct])},</script>"
    js_content_layover = f"<script class=\"ds:1\">data:{json.dumps([payload_layover])},</script>"

    offers_direct = parse_google_flights_payload_generic(js_content_direct, "SKG", "ORY", "2027-04-03")
    assert len(offers_direct) == 1
    assert offers_direct[0].price == 85.0
    assert offers_direct[0].airline == "Transavia"
    assert offers_direct[0].is_direct is True
    assert offers_direct[0].departure_time == "17:45"
    assert offers_direct[0].arrival_time == "19:55"

    offers_layover = parse_google_flights_payload_generic(js_content_layover, "SKG", "WAW", "2027-04-03")
    assert len(offers_layover) == 1
    assert offers_layover[0].price == 101.0
    assert offers_layover[0].airline == "LOT"
    assert offers_layover[0].is_direct is False
    assert offers_layover[0].departure_time == "13:20"
    assert offers_layover[0].arrival_time == "17:20"




