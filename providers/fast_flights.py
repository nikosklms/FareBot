import asyncio
import json
import logging
import time
import urllib.parse
from collections import deque
from http.cookiejar import CookieJar, DefaultCookiePolicy
from datetime import date
from typing import Any, List, Optional

import httpx
from fast_flights import FlightQuery, Passengers, create_query
from selectolax.lexbor import LexborHTMLParser

from providers.base import AbstractFlightProvider, FlightOffer
from services.airports_data import MULTI_AIRPORT_CITIES
from utils.date_parser import generate_date_sequence

logger = logging.getLogger(__name__)

# Concurrent Google Flights requests. Measured with tools/benchmark.py (2026-10-30): 5 gave
# 434 queries/min sustained over 300 queries with no rate limiting; 8 was faster but each
# request slowed down and CPU and memory climbed. Rerun the benchmark before raising it.
CONCURRENT_REQUESTS = 5


class GoogleRateLimitException(Exception):
    """Raised when Google Flights returns a CAPTCHA challenge or HTTP 429/403 rate limit response."""


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
RATE_LIMIT_STATUSES = (429, 403, 503)
CAPTCHA_MARKERS = ("unusual traffic", "sorry/index", '<div id="recaptcha"', "title>429")


class GoogleFlightsClient:
    """Fetches Google Flights result pages over one long-lived HTTP client.

    Reusing connections matters: in the EU every query is redirected through
    consent.google.com, so opening fresh connections meant up to three TLS handshakes
    per query. Asking for compression cuts each page from about 2.4 MB to 0.3 MB.

    Cookies are never stored. The redirect sets a "consent pending" cookie, and when it
    is sent back Google shows its consent page instead of the flight results.
    """

    def __init__(self, timeout: float = 12.0, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._timeout = timeout
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=BROWSER_HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=30),
                cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
                transport=self._transport,
            )
        return self._client

    async def fetch_html(self, q) -> str:
        url = f"https://www.google.com/travel/flights?{urllib.parse.urlencode(q.params())}"
        t0 = time.perf_counter()
        try:
            response = await self._http().get(url)
        except httpx.HTTPError as e:
            logger.error(f"[HTTP_FAIL] {type(e).__name__} fetching Google Flights after "
                         f"{(time.perf_counter() - t0) * 1000.0:.0f}ms: {e}")
            raise
        logger.debug(f"[HTTP] Google Flights response: status={response.status_code}, "
                     f"size={len(response.content)} bytes, latency={(time.perf_counter() - t0) * 1000.0:.0f}ms")

        if response.status_code in RATE_LIMIT_STATUSES:
            logger.warning(f"[RATE_LIMIT] Received HTTP {response.status_code} status from Google Flights! "
                           "Possible rate limiting.")
            raise GoogleRateLimitException(f"HTTP {response.status_code}")
        response.raise_for_status()

        html = response.text
        if any(marker in html.lower() for marker in CAPTCHA_MARKERS):
            logger.error(f"[RATE_LIMIT] CAPTCHA / Rate limit page detected from Google Flights! ({url[:80]})")
            raise GoogleRateLimitException(f"Google Rate Limit / CAPTCHA detected for {url[:80]}")
        return html

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_google_flights_url(
    origin: str,
    destination: str,
    departure_date: str,
    currency: str = "EUR",
    direct_only: bool = False
) -> str:
    """Construct a valid Google Flights search URL with protobuf tfs parameter."""
    try:
        q = create_query(
            flights=[FlightQuery(date=departure_date, from_airport=origin, to_airport=destination)],
            passengers=Passengers(adults=1),
            currency=currency
        )
        params = q.params()
        if direct_only:
            params["max_stops"] = 0
        return f"https://www.google.com/travel/flights/search?{urllib.parse.urlencode(params)}"
    except Exception as e:
        logger.warning(f"Failed to generate Google Flights tfs URL: {e}")
        text_query = f"Flights from {origin} to {destination} on {departure_date}"
        return f"https://www.google.com/travel/flights?q={urllib.parse.quote(text_query)}&curr={currency}"

def _extract_typical_price_range(payload: Any) -> tuple[Optional[float], Optional[float]]:
    """Extract typical min and max price baseline range from Google Flights JSON payload."""
    # Strategy 1: Direct lookup in payload[5] price insight node if present
    if isinstance(payload, list) and len(payload) > 5 and isinstance(payload[5], list):
        p5 = payload[5]
        if len(p5) >= 6:
            if isinstance(p5[4], list) and len(p5[4]) >= 2 and isinstance(p5[4][1], (int, float)):
                if isinstance(p5[5], list) and len(p5[5]) >= 2 and isinstance(p5[5][1], (int, float)):
                    min_val, max_val = float(p5[4][1]), float(p5[5][1])
                    if 15 <= min_val <= 3000 and 20 <= max_val <= 5000 and max_val > min_val:
                        return min_val, max_val

    # Strategy 2: Walk for explicit Google price insight node structure [enum_val, [None, curr], ..., [None, min], [None, max]]
    candidates = []
    def _walk(obj):
        if isinstance(obj, list):
            if len(obj) >= 6:
                for i in range(len(obj) - 1):
                    item1, item2 = obj[i], obj[i+1]
                    if (isinstance(item1, list) and len(item1) >= 2 and item1[0] is None and isinstance(item1[1], (int, float)) and
                        isinstance(item2, list) and len(item2) >= 2 and item2[0] is None and isinstance(item2[1], (int, float))):
                        v1, v2 = float(item1[1]), float(item2[1])
                        # Filter out time arrays like [13, 25] or [14, 10]
                        if 15 <= v1 <= 3000 and 20 <= v2 <= 5000 and (v2 - v1) >= 10:
                            candidates.append((v1, v2))
            for child in obj:
                _walk(child)

    _walk(payload)
    if candidates:
        return candidates[0]
    return None, None

def parse_google_flights_payload_generic(
    html: str,
    default_origin: str,
    default_destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    currency: str = "EUR"
) -> List[FlightOffer]:
    """Parse Google Flights html JSON payload and extract matching flight offers."""
    html_lower = html.lower()
    if "unusual traffic" in html_lower or "sorry/index" in html_lower:
        raise GoogleRateLimitException("Google Rate Limit / CAPTCHA detected in HTML payload")

    offers: List[FlightOffer] = []
    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if not script:
        logger.warning(f"[PARSER_WARN] Could not find script.ds:1 tag in HTML response for {default_origin} -> {default_destination} ({len(html)} bytes)")
        return offers

    try:
        js = script.text()
        data_str = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data_str)
    except Exception as e:
        logger.warning(f"[PARSER_WARN] Failed to parse script.ds:1 JSON payload for {default_origin} -> {default_destination}: {e}")
        return offers

    typical_min, typical_max = _extract_typical_price_range(payload)
    if typical_min or typical_max:
        logger.debug(f"[PARSER] Extracted typical price baseline range for {default_origin}->{default_destination}: €{typical_min} - €{typical_max}")

    def _walk(obj):
        if not isinstance(obj, list):
            return

        flight_info = None
        price_val = None

        for elem in obj:
            if isinstance(elem, list):
                # Valid flight_info node: contains airline list at index 1 and legs list at index 2
                if len(elem) >= 3 and isinstance(elem[1], list) and isinstance(elem[2], list) and len(elem[2]) > 0:
                    first_leg = elem[2][0]
                    # Verify first_leg is a valid segment with full flight details (len > 22 and flight segment metadata)
                    if isinstance(first_leg, list) and len(first_leg) > 22 and isinstance(first_leg[22], list):
                        flight_info = elem

                # Valid price_info node: contains [None, price_number] or [price_number]
                if len(elem) >= 1 and isinstance(elem[0], list) and len(elem[0]) >= 2:
                    if elem[0][0] is None and isinstance(elem[0][1], (int, float)):
                        price_val = float(elem[0][1])

        if flight_info and price_val is not None and price_val > 0:
            raw_airlines = flight_info[1] if isinstance(flight_info[1], list) else []
            clean_airlines = [a for a in raw_airlines if isinstance(a, str) and not a.startswith("http") and len(a) < 40]
            airline_name = ", ".join(clean_airlines) if clean_airlines else "Various Airlines"

            legs = flight_info[2]
            valid_legs = [l for l in legs if isinstance(l, list)] if isinstance(legs, list) else []
            first_leg = valid_legs[0] if valid_legs else []
            orig_val = first_leg[3] if len(first_leg) > 3 else None
            dest_val = valid_legs[-1][6] if valid_legs and len(valid_legs[-1]) > 6 else None

            sub_segments = first_leg[22] if (len(first_leg) > 22 and isinstance(first_leg[22], list)) else []
            valid_sub_segs = [s for s in sub_segments if isinstance(s, list) and len(s) > 5] if sub_segments else []
            if len(valid_legs) > 1:
                is_direct_flight = False
            elif valid_sub_segs:
                is_direct_flight = (len(valid_sub_segs) == 1)
            elif valid_legs:
                is_direct_flight = (len(valid_legs) == 1)
            else:
                is_direct_flight = False

            def _fmt_t(t_list):
                if isinstance(t_list, list) and len(t_list) >= 2 and isinstance(t_list[0], int) and isinstance(t_list[1], int):
                    return f"{t_list[0]:02d}:{t_list[1]:02d}"
                return None

            def _calc_day_offset(dep_d_list, arr_d_list):
                try:
                    if isinstance(dep_d_list, list) and len(dep_d_list) >= 3 and isinstance(arr_d_list, list) and len(arr_d_list) >= 3:
                        d1 = date(dep_d_list[0], dep_d_list[1], dep_d_list[2])
                        d2 = date(arr_d_list[0], arr_d_list[1], arr_d_list[2])
                        return max(0, (d2 - d1).days)
                except Exception:
                    pass
                return 0

            dep_time = _fmt_t(valid_legs[0][8]) if valid_legs and len(valid_legs[0]) > 8 else None
            arr_time = _fmt_t(valid_legs[-1][10]) if valid_legs and len(valid_legs[-1]) > 10 else None

            dep_d_raw = valid_legs[0][20] if valid_legs and len(valid_legs[0]) > 20 else None
            arr_d_raw = valid_legs[-1][21] if valid_legs and len(valid_legs[-1]) > 21 else None
            day_offset_val = _calc_day_offset(dep_d_raw, arr_d_raw)

            orig = orig_val if isinstance(orig_val, str) and len(orig_val) == 3 else default_origin
            dest = dest_val if isinstance(dest_val, str) and len(dest_val) == 3 else default_destination

            booking_url_val = build_google_flights_url(orig, dest, departure_date, currency=currency)

            if len(orig) == 3 and len(dest) == 3 and orig.isalpha() and dest.isalpha():
                offers.append(
                    FlightOffer(
                        origin=orig,
                        destination=dest,
                        departure_date=departure_date,
                        return_date=return_date,
                        price=price_val,
                        currency=currency,
                        airline=airline_name,
                        is_direct=is_direct_flight,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        day_offset=day_offset_val,
                        typical_min=typical_min,
                        typical_max=typical_max,
                        booking_url=booking_url_val
                    )
                )

        for child in obj:
            _walk(child)

    _walk(payload)

    # The payload lists some flights more than once; different flights at the same price stay.
    unique_offers: List[FlightOffer] = []
    seen = set()
    for offer in offers:
        key = (offer.price, offer.airline, offer.origin, offer.destination, offer.departure_time, offer.arrival_time)
        if key not in seen:
            seen.add(key)
            unique_offers.append(offer)

    # Sort strictly ascending by numerical float price so lowest price option is ALWAYS #1
    unique_offers.sort(key=lambda x: x.price)
    logger.debug(f"[PARSER] {default_origin} -> {default_destination}: Extracted {len(offers)} raw offers, {len(unique_offers)} unique offers")
    return unique_offers

def _is_summary(offer: FlightOffer) -> bool:
    return offer.airline == "Various Airlines" or offer.departure_time is None


def merge_duplicate_offers(offers: List[FlightOffer]) -> List[FlightOffer]:
    """Drop repeats of the same flight while keeping different flights that share a price.

    Google often lists a fare twice: as a summary card ("Various Airlines", no times)
    and as a detailed card. A summary card is kept only when no detailed card has its price.
    """
    groups: dict[tuple[float, str, str, str], List[FlightOffer]] = {}
    for offer in offers:
        groups.setdefault((offer.price, offer.departure_date, offer.origin, offer.destination), []).append(offer)

    merged: List[FlightOffer] = []
    for group in groups.values():
        detailed = [o for o in group if not _is_summary(o)]
        seen = set()
        for offer in detailed or group[:1]:
            key = (offer.airline, offer.departure_time, offer.arrival_time, offer.is_direct)
            if key not in seen:
                seen.add(key)
                merged.append(offer)
    return merged


class FastFlightsProvider(AbstractFlightProvider):
    """Google Flights scraper built on fast-flights query encoding."""

    concurrency = CONCURRENT_REQUESTS

    def __init__(self, client: Optional[GoogleFlightsClient] = None) -> None:
        self._fetcher = client or GoogleFlightsClient()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._latencies: deque[float] = deque(maxlen=100)

    def average_latency(self) -> float:
        if not self._latencies:
            return 0.5
        return sum(self._latencies) / len(self._latencies)

    def latency_samples(self) -> list[float]:
        """Seconds per Google request (fetch and parse, not queue time), last 100 requests."""
        return list(self._latencies)

    async def close(self) -> None:
        await self._fetcher.close()

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)

        target_destinations = MULTI_AIRPORT_CITIES.get(destination.upper(), [destination])
        t_start = time.perf_counter()

        results = await asyncio.gather(*(
            self._fetch(origin, dest, departure_date, return_date, currency, direct_only)
            for dest in target_destinations
        ))
        all_offers = [offer for batch in results for offer in batch]

        offers = merge_duplicate_offers([o for o in all_offers if o.is_direct or not direct_only])
        offers.sort(key=lambda o: o.price)
        logger.debug(
            f"[PROVIDER] {origin} -> {destination} on {departure_date}: {len(offers)} offers "
            f"in {(time.perf_counter() - t_start) * 1000.0:.0f}ms"
        )
        return offers

    async def _fetch(
        self,
        origin: str,
        dest_code: str,
        departure_date: str,
        return_date: Optional[str],
        currency: str,
        direct_only: bool,
    ) -> List[FlightOffer]:
        flight_queries = [FlightQuery(date=departure_date, from_airport=origin, to_airport=dest_code)]
        if return_date:
            flight_queries.append(FlightQuery(date=return_date, from_airport=dest_code, to_airport=origin))
        query_kwargs: dict[str, Any] = {
            "flights": flight_queries,
            "trip": "round-trip" if return_date else "one-way",
            "passengers": Passengers(adults=1),
            "currency": currency,
        }
        if direct_only:
            query_kwargs["max_stops"] = 0
        q = create_query(**query_kwargs)

        max_retries = 2
        async with self._semaphore:
            t0 = time.perf_counter()
            for attempt in range(max_retries + 1):
                try:
                    html = await self._fetcher.fetch_html(q)
                    # Parsing a results page takes tens of milliseconds; keep it off the event loop.
                    offers = await asyncio.to_thread(parse_google_flights_payload_generic, html, origin, dest_code,
                                                     departure_date, return_date, currency)
                    self._latencies.append(time.perf_counter() - t0)
                    return offers
                except GoogleRateLimitException as e:
                    if attempt == max_retries:
                        logger.error(f"[PROVIDER_ERR] Max retries reached for {origin} -> {dest_code}: {e}")
                        return []
                    backoff_sec = 0.5 * (2 ** attempt)
                    logger.warning(f"[RATE_LIMIT_RETRY] {e}. Retrying {origin} -> {dest_code} in {backoff_sec}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(backoff_sec)
                except Exception as e:
                    logger.error(f"[PROVIDER_ERR] Error fetching flights for {origin} -> {dest_code} on {departure_date}: {e}")
                    return []
        return []

    async def search_flights_range(
        self,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        currency: str = "EUR",
        direct_only: bool = False,
    ) -> List[FlightOffer]:
        dates = generate_date_sequence(start_date, end_date)
        results = await asyncio.gather(*(
            self.search_flights(origin=origin, destination=destination, departure_date=d,
                                currency=currency, direct_only=direct_only)
            for d in dates
        ))
        offers = [offer for batch in results for offer in batch]
        offers.sort(key=lambda o: o.price)
        logger.info(f"[PROVIDER] Range search {origin} -> {destination} across {len(dates)} dates: {len(offers)} offers")
        return offers
