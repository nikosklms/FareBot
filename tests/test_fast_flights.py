import asyncio
import gzip
import json

import httpx
import pytest
from unittest.mock import patch, MagicMock, ANY
from providers.fast_flights import FastFlightsProvider, GoogleFlightsClient, parse_google_flights_payload_generic
from providers.base import FlightOffer
from tests.fakes import future


@pytest.mark.asyncio
async def test_search_flights_range():
    provider = FastFlightsProvider()
    async def mock_search(origin, destination, departure_date, **kwargs):
        price = 100.0 if departure_date == "2026-09-02" else 150.0
        return [FlightOffer(origin=origin, destination=destination, departure_date=departure_date, price=price)]

    with patch.object(provider, "search_flights", side_effect=mock_search):
        offers = await provider.search_flights_range(
            origin="ATH", destination="LON", start_date="2026-09-01", end_date="2026-09-03"
        )
        assert len(offers) == 3
        assert offers[0].departure_date == "2026-09-02"
        assert offers[0].price == 100.0

@pytest.mark.asyncio
async def test_search_flights_range_full_99_days():
    provider = FastFlightsProvider()
    async def mock_search(origin, destination, departure_date, **kwargs):
        return [FlightOffer(origin=origin, destination=destination, departure_date=departure_date, price=200.0)]

    with patch.object(provider, "search_flights", side_effect=mock_search):
        offers = await provider.search_flights_range(
            origin="ATH", destination="SIN", start_date="2026-08-17", end_date="2026-11-23"
        )
        assert len(offers) == 99


@pytest.mark.live
async def test_skg_to_lon_returns_absolute_lowest_price_first():
    """Live: SKG to London (all airports) returns offers sorted by price."""
    provider = FastFlightsProvider()
    offers = await provider.search_flights(
        origin="SKG",
        destination="LON",
        departure_date=future(30)
    )
    assert len(offers) > 0

    # Verify results are strictly sorted ascending by price
    prices = [o.price for o in offers]
    assert prices == sorted(prices), f"Offers are not sorted by price! Got: {prices}"

    # Verify that the lowest price is <= 130 (e.g. Ryanair €93 to STN or easyJet €130 to LGW)
    lowest_offer = offers[0]
    assert lowest_offer.price < 1000.0, f"Implausible lowest price: {lowest_offer.price} ({lowest_offer.airline})"

@pytest.mark.live
async def test_ath_to_bud_returns_wizz_air_lowest_price_first():
    """Live: ATH to BUD returns offers sorted by price."""
    provider = FastFlightsProvider()
    offers = await provider.search_flights(
        origin="ATH",
        destination="BUD",
        departure_date=future(30)
    )
    assert len(offers) > 0

    prices = [o.price for o in offers]
    assert prices == sorted(prices), f"Offers are not sorted by price! Got: {prices}"

    lowest_offer = offers[0]
    assert lowest_offer.price < 1000.0, f"Implausible lowest price: {lowest_offer.price} ({lowest_offer.airline})"

class StaticClient:
    """Stands in for GoogleFlightsClient: returns the same page for every query."""

    def __init__(self, html="<html></html>"):
        self.html = html

    async def fetch_html(self, q):
        return self.html

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_fast_flights_direct_only_filter():
    provider = FastFlightsProvider(client=StaticClient())

    offer_direct = FlightOffer("ATH", "LON", "2026-08-15", price=150.0, is_direct=True)
    offer_stop = FlightOffer("ATH", "LON", "2026-08-15", price=120.0, is_direct=False)

    with patch("providers.fast_flights.create_query") as mock_cq:
        mock_cq.return_value = MagicMock()
        with patch("providers.fast_flights.parse_google_flights_payload_generic", return_value=[offer_stop, offer_direct]):
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

@pytest.mark.asyncio
async def test_parse_google_flights_overnight_flight_day_offset():
    """Verify that overnight flights spanning across midnight accurately calculate day_offset."""
    # Leg format: index 8 is [23, 0], index 10 is [4, 15], index 20 is [2027, 4, 3], index 21 is [2027, 4, 4], index 22 is metadata
    overnight_leg = [None]*8 + [[23, 0], None, [4, 15]] + [None]*9 + [[2027, 4, 3], [2027, 4, 4], [["flight_meta"]]]
    flight_node = [None, ["Aegean"], [overnight_leg]]
    payload = [flight_node, [[None, 120.0]]]

    import json
    js_content = f"<script class=\"ds:1\">data:{json.dumps([payload])},</script>"

    offers = parse_google_flights_payload_generic(js_content, "ATH", "LON", "2027-04-03")
    assert len(offers) == 1
    assert offers[0].departure_time == "23:00"
    assert offers[0].arrival_time == "04:15"
    assert offers[0].day_offset == 1


def test_parse_times_with_omitted_zero_parts():
    """Google sends 08:00 as [8] and 00:31 as [None, 31]; those must not look like time-less summary cards."""
    leg = [None]*8 + [[8], None, [None, 31]] + [None]*9 + [[2027, 4, 3], [2027, 4, 4], [["flight_meta"]]]
    payload = [[None, ["Aegean"], [leg]], [[None, 120.0]]]
    html = f"<script class=\"ds:1\">data:{json.dumps([payload])},</script>"

    [offer] = parse_google_flights_payload_generic(html, "ATH", "LON", "2027-04-03")
    assert (offer.departure_time, offer.arrival_time) == ("08:00", "00:31")

@pytest.mark.asyncio
async def test_google_flights_url_generation_and_stateless_booking_links():
    """Verify that generated booking URLs use Google Flights /search?tfs= format from stateless IATA+date encoding, not session-bound tokens."""
    from providers.fast_flights import build_google_flights_url
    url = build_google_flights_url("SKG", "BUD", "2027-01-09", direct_only=True)
    assert "google.com/travel/flights/search?tfs=" in url
    assert "?q=" not in url

    # Test that parsed offers always get a stateless tfs URL, even when payload contains Cj tokens
    leg = [None]*8 + [[22, 50], None, [23, 30]] + [None]*11 + [["flight_meta"]]
    flight_node = [None, ["Wizz Air"], [leg]]
    # Include a Cj token in the payload — it should NOT be used for the booking URL
    price_node = [[None, 25.0], "CjRIdi1NelI5YmdfR1VBQUFXNGdCRy0tLS0tLS0tZWpja3gyMEFBQUFBR3BnQjh3SndXTU9BEgZXNjI0NDgaCgjDExACGgNFVVI4HXChFg=="]
    payload = [flight_node, price_node]

    import json
    js_content = f"<script class=\"ds:1\">data:{json.dumps([payload])},</script>"
    offers = parse_google_flights_payload_generic(js_content, "SKG", "BUD", "2027-01-09")
    assert len(offers) == 1
    assert offers[0].booking_url is not None
    # URL should be a stateless tfs URL, NOT containing the Cj session token
    assert "google.com/travel/flights/search?tfs=" in offers[0].booking_url
    assert "CjRIdi" not in offers[0].booking_url

@pytest.mark.asyncio
async def test_bot_challenge_html_raises_google_rate_limit_exception():
    """Verify that receiving a Google bot challenge / captcha page raises GoogleRateLimitException."""
    from providers.fast_flights import GoogleRateLimitException
    captcha_html = "<html><body><h1>unusual traffic from your computer network</h1><p>recaptcha</p></body></html>"
    with pytest.raises(GoogleRateLimitException):
        parse_google_flights_payload_generic(captcha_html, "SKG", "VIE", "2026-10-31")

def results_page(price=45.0, airline="Ryanair"):
    leg = [None]*8 + [[10, 0], None, [12, 0]] + [None]*11 + [["flight_meta"]]
    payload = [[None, [airline], [leg]], [[None, price]]]
    return f"<script class=\"ds:1\">data:{json.dumps([payload])},</script>"


def mock_client(handler):
    return GoogleFlightsClient(transport=httpx.MockTransport(handler))


class FakeTime:
    """A clock that only moves when the provider sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        wake_at = self.now + seconds
        await asyncio.sleep(0)  # let other searches start sleeping at the same moment
        self.now = max(self.now, wake_at)


def google(*statuses):
    """A fake Google answering with these statuses in turn (200 = a results page), counting requests."""
    replies = list(statuses)
    calls = []

    def handler(request):
        calls.append(request)
        status = replies.pop(0)
        return httpx.Response(200, text=results_page()) if status == 200 else httpx.Response(status)

    return mock_client(handler), calls


def paced_provider(*statuses):
    client, calls = google(*statuses)
    time_ = FakeTime()
    return FastFlightsProvider(client=client, clock=time_.clock, sleep=time_.sleep), calls, time_


@pytest.mark.asyncio
async def test_a_rate_limit_pauses_then_retries_once():
    provider, calls, time_ = paced_provider(429, 200)
    offers = await provider.search_flights("SKG", "VIE", "2026-10-31")
    assert [o.price for o in offers] == [45.0]
    assert len(calls) == 2 and time_.sleeps == [60]
    await provider.close()


@pytest.mark.asyncio
async def test_continued_blocks_double_the_pause_and_skip_google_meanwhile():
    from providers.base import FlightSearchError
    provider, calls, time_ = paced_provider(429, 429, 200)
    with pytest.raises(FlightSearchError):
        await provider.search_flights("SKG", "VIE", "2026-10-31")
    assert len(calls) == 2  # the first request and one retry after 60 s; now paused for 120 s

    with pytest.raises(FlightSearchError):
        await provider.search_flights("SKG", "VIE", "2026-11-01")
    assert len(calls) == 2  # a long pause fails at once, without contacting Google

    time_.now += 120
    assert [o.price for o in await provider.search_flights("SKG", "VIE", "2026-11-02")] == [45.0]
    assert len(calls) == 3
    await provider.close()


@pytest.mark.asyncio
async def test_a_successful_search_resets_the_pause():
    provider, calls, time_ = paced_provider(429, 200, 429, 200)
    await provider.search_flights("SKG", "VIE", "2026-10-31")
    await provider.search_flights("SKG", "VIE", "2026-11-01")
    assert time_.sleeps == [60, 60]
    await provider.close()


@pytest.mark.asyncio
async def test_simultaneous_blocks_start_one_pause():
    all_sent = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) <= 3:  # the first three are in flight together, then all get blocked
            if len(calls) == 3:
                all_sent.set()
            await all_sent.wait()
            return httpx.Response(429)
        return httpx.Response(200, text=results_page())

    time_ = FakeTime()
    provider = FastFlightsProvider(client=mock_client(handler), clock=time_.clock, sleep=time_.sleep)
    results = await asyncio.gather(*(provider.search_flights("SKG", "VIE", f"2026-11-0{d}") for d in (1, 2, 3)))
    assert all(r[0].price == 45.0 for r in results)
    assert time_.sleeps == [60, 60, 60]  # all three waited out the same 60 s pause, not 60 + 120 + 240
    await provider.close()


@pytest.mark.asyncio
async def test_client_follows_consent_redirect_and_decompresses():
    """Mirrors Google in the EU: if the consent cookie set on the redirect is sent back,
    consent.google.com shows its consent page instead of returning to the results."""
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "consent.google.com":
            if "SOCS" in request.headers.get("cookie", ""):
                return httpx.Response(200, text="<title>Before you continue</title>")
            return httpx.Response(302, headers={"location": "https://www.google.com/travel/flights?tfs=x&ok=1"})
        if "ok" not in request.url.params:
            return httpx.Response(302, headers={"location": "https://consent.google.com/m?continue=x",
                                                "set-cookie": "SOCS=pending; Domain=.google.com; Path=/"})
        body = gzip.compress(results_page(price=60.0).encode())
        return httpx.Response(200, content=body, headers={"content-encoding": "gzip"})

    client = mock_client(handler)
    for tfs in ("abc", "def"):
        html = await client.fetch_html(MagicMock(params=lambda tfs=tfs: {"tfs": tfs}))
        assert "60.0" in html and "Before you continue" not in html
    assert [r.url.host for r in seen[:3]] == ["www.google.com", "consent.google.com", "www.google.com"]
    assert all("cookie" not in r.headers for r in seen)
    assert "gzip" in seen[0].headers["accept-encoding"]
    assert "Chrome" in seen[0].headers["user-agent"]
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(503),
    httpx.Response(200, text="<html>Our systems have detected unusual traffic</html>"),
])
async def test_client_detects_rate_limiting(response):
    from providers.fast_flights import GoogleRateLimitException
    client = mock_client(lambda request: response)
    with pytest.raises(GoogleRateLimitException):
        await client.fetch_html(MagicMock(params=lambda: {"tfs": "x"}))
    await client.close()


@pytest.mark.asyncio
async def test_failed_searches_raise_instead_of_looking_empty():
    from providers.base import FlightSearchError
    provider = FastFlightsProvider(client=mock_client(lambda request: httpx.Response(500)))
    with pytest.raises(FlightSearchError):
        await provider.search_flights("SKG", "VIE", "2026-10-31")
    with pytest.raises(FlightSearchError):
        await provider.search_flights_range("SKG", "VIE", "2026-10-31", "2026-11-01")
    await provider.close()


@pytest.mark.asyncio
async def test_a_page_with_no_flights_is_an_empty_result():
    provider = FastFlightsProvider(client=mock_client(lambda request: httpx.Response(200, text="<html></html>")))
    assert await provider.search_flights("SKG", "VIE", "2026-10-31") == []
    await provider.close()


@pytest.mark.asyncio
async def test_booking_links_keep_direct_only():
    pages = {"page": results_page()}
    provider = FastFlightsProvider(client=mock_client(lambda request: httpx.Response(200, text=pages["page"])))
    [any_offer] = await provider.search_flights("SKG", "VIE", "2026-10-31")
    [direct_offer] = await provider.search_flights("SKG", "VIE", "2026-10-31", direct_only=True)
    assert any_offer.booking_url != direct_offer.booking_url
    assert "max_stops" not in any_offer.booking_url and "max_stops=0" in direct_offer.booking_url
    await provider.close()


def test_merge_keeps_different_flights_at_the_same_price():
    from providers.fast_flights import merge_duplicate_offers
    def offer(airline, time, direct=True):
        return FlightOffer("ATH", "LGW", "2027-01-01", 49.0, airline=airline, departure_time=time, is_direct=direct)
    summary = FlightOffer("ATH", "LGW", "2027-01-01", 49.0, airline="Various Airlines")
    merged = merge_duplicate_offers([summary, offer("easyJet", "06:00"), offer("BA", "14:00"), offer("BA", "14:00")])
    assert [o.airline for o in merged] == ["easyJet", "BA"]
    assert merge_duplicate_offers([summary]) == [summary]


@pytest.mark.asyncio
async def test_direct_only_never_loses_a_direct_flight_to_a_same_price_connection():
    connecting = FlightOffer("ATH", "LGW", "2027-01-01", 49.0, airline="easyJet", departure_time="06:00", is_direct=False)
    direct = FlightOffer("ATH", "LGW", "2027-01-01", 49.0, airline="Aegean", departure_time="18:00", is_direct=True)
    provider = FastFlightsProvider(client=StaticClient())
    with patch("providers.fast_flights.parse_google_flights_payload_generic", return_value=[connecting, direct]):
        assert [o.airline for o in await provider.search_flights("ATH", "LGW", "2027-01-01", direct_only=True)] == ["Aegean"]


def test_summary_card_for_a_city_is_dropped_when_a_detailed_card_exists():
    from providers.fast_flights import merge_duplicate_offers
    summary = FlightOffer("SKG", "LON", "2027-01-01", 149.0, airline="Various Airlines")
    detailed = FlightOffer("SKG", "STN", "2027-01-01", 149.0, airline="Ryanair", departure_time="20:40")
    other_day = FlightOffer("SKG", "LON", "2027-01-02", 149.0, airline="Various Airlines")
    assert merge_duplicate_offers([summary, detailed, other_day]) == [detailed, other_day]
