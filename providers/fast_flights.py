import logging
import asyncio
import urllib.request
import urllib.parse
import urllib.error
import time
import json
from typing import List, Optional, Any
from selectolax.lexbor import LexborHTMLParser
from fast_flights import create_query, FlightQuery, Passengers
from fast_flights.integrations.base import FetchIntegration
from providers.base import AbstractFlightProvider, FlightOffer
from services.airports_data import MULTI_AIRPORT_CITIES

logger = logging.getLogger(__name__)

class GoogleRateLimitException(Exception):
    """Raised when Google Flights returns a CAPTCHA challenge or HTTP 429/403 rate limit response."""
    pass

# Class-level shared semaphore to limit concurrent Google Flights HTTP requests across all callers
_GLOBAL_SEMAPHORE: Optional[asyncio.Semaphore] = None

def get_shared_semaphore(limit: int = 3) -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE

class UrllibFetchIntegration(FetchIntegration):
    """Custom reliable HTTP fetcher for Google Flights to prevent TLS fingerprinting hangs."""
    def fetch_html(self, q) -> str:
        if isinstance(q, str):
            url = f"https://www.google.com/travel/flights?q={urllib.parse.quote(q)}"
        else:
            url = f"https://www.google.com/travel/flights?{urllib.parse.urlencode(q.params())}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        t0 = time.perf_counter()
        logger.debug(f"[HTTP] Requesting Google Flights: {url[:100]}...")
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                status_code = getattr(response, "status", 200)
                raw_bytes = response.read()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                content_len = len(raw_bytes)
                logger.info(f"[HTTP] Google Flights response: status={status_code}, size={content_len} bytes, latency={elapsed_ms:.1f}ms")

                html = raw_bytes.decode("utf-8", errors="ignore")

                # Check for genuine rate-limiting / CAPTCHA block signatures
                html_lower = html.lower()
                if "unusual traffic" in html_lower or "sorry/index" in html_lower or "<div id=\"recaptcha\"" in html_lower or "title>429" in html_lower:
                    logger.error(f"[RATE_LIMIT] CAPTCHA / Rate limit page detected from Google Flights! ({url[:80]})")
                    raise GoogleRateLimitException(f"Google Rate Limit / CAPTCHA detected for {url[:80]}")

                return html
        except urllib.error.HTTPError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.error(f"[HTTP_ERROR] HTTP {e.code} error fetching Google Flights ({e.reason}) after {elapsed_ms:.1f}ms for {url[:80]}")
            if e.code in (429, 403, 503):
                logger.warning(f"[RATE_LIMIT] Received HTTP {e.code} status from Google Flights! Possible rate limiting.")
                raise GoogleRateLimitException(f"HTTP {e.code}: {e.reason}")
            raise
        except Exception as e:
            if isinstance(e, GoogleRateLimitException):
                raise
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.error(f"[HTTP_FAIL] Exception fetching Google Flights after {elapsed_ms:.1f}ms: {e}")
            raise

def build_google_flights_url(
    origin: str,
    destination: str,
    departure_date: str,
    currency: str = "EUR",
    direct_only: bool = False
) -> str:
    """Construct a valid Google Flights search URL with protobuf tfs parameter."""
    try:
        from fast_flights import create_query, FlightQuery, Passengers
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
        return f"https://www.google.com/travel/flights/search?tfs=GhoSC{departure_date}jBRID{origin}rUSA{destination}&curr={currency}"

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
            orig_val = valid_legs[0][3] if valid_legs and len(valid_legs[0]) > 3 else None
            dest_val = valid_legs[-1][6] if valid_legs and len(valid_legs[-1]) > 6 else None
            is_direct_flight = (len(valid_legs) == 1) if valid_legs else True

            def _fmt_t(t_list):
                if isinstance(t_list, list) and len(t_list) >= 2 and isinstance(t_list[0], int) and isinstance(t_list[1], int):
                    return f"{t_list[0]:02d}:{t_list[1]:02d}"
                return None

            def _calc_day_offset(dep_d_list, arr_d_list):
                try:
                    if isinstance(dep_d_list, list) and len(dep_d_list) >= 3 and isinstance(arr_d_list, list) and len(arr_d_list) >= 3:
                        from datetime import date
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

    # Deduplicate offers by (price, airline, origin, destination)
    unique_offers: List[FlightOffer] = []
    seen = set()
    for offer in offers:
        key = (offer.price, offer.airline, offer.origin, offer.destination)
        if key not in seen:
            seen.add(key)
            unique_offers.append(offer)

    # Sort strictly ascending by numerical float price so lowest price option is ALWAYS #1
    unique_offers.sort(key=lambda x: x.price)
    logger.debug(f"[PARSER] {default_origin} -> {default_destination}: Extracted {len(offers)} raw offers, {len(unique_offers)} unique offers")
    return unique_offers

class FastFlightsProvider(AbstractFlightProvider):
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        loop = asyncio.get_running_loop()
        fetcher = UrllibFetchIntegration()

        target_destinations = MULTI_AIRPORT_CITIES.get(destination.upper(), [destination])
        sem = get_shared_semaphore(3)

        t_start = time.perf_counter()
        logger.info(f"[PROVIDER] Starting flight search: {origin} -> {destination} ({target_destinations}) on {departure_date} (direct_only={direct_only})")

        async def _fetch_for_dest(dest_code: str) -> List[FlightOffer]:
            sem_t0 = time.perf_counter()
            async with sem:
                sem_wait = (time.perf_counter() - sem_t0) * 1000.0
                if sem_wait > 50.0:
                    logger.debug(f"[CONCURRENCY] Waited {sem_wait:.1f}ms to acquire HTTP semaphore for {origin} -> {dest_code}")

                flight_queries = [FlightQuery(date=departure_date, from_airport=origin, to_airport=dest_code)]
                if return_date:
                    flight_queries.append(FlightQuery(date=return_date, from_airport=dest_code, to_airport=origin))

                query_kwargs = {
                    "flights": flight_queries,
                    "trip": "round-trip" if return_date else "one-way",
                    "passengers": Passengers(adults=1),
                    "currency": currency
                }
                if direct_only:
                    query_kwargs["max_stops"] = 0

                q = create_query(**query_kwargs)

                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        html = await loop.run_in_executor(None, lambda: fetcher.fetch_html(q))
                        res_offers = parse_google_flights_payload_generic(html, origin, dest_code, departure_date, return_date, currency)
                        return res_offers
                    except GoogleRateLimitException as e:
                        if attempt < max_retries:
                            backoff_sec = 0.5 * (2 ** attempt)
                            logger.warning(f"[RATE_LIMIT_RETRY] {e}. Retrying {origin} -> {dest_code} in {backoff_sec}s (attempt {attempt+1}/{max_retries})...")
                            await asyncio.sleep(backoff_sec)
                        else:
                            logger.error(f"[PROVIDER_ERR] Max retries reached for {origin} -> {dest_code}: {e}")
                            return []
                    except Exception as e:
                        logger.error(f"[PROVIDER_ERR] Error fetching flights for {origin} -> {dest_code} on {departure_date}: {e}")
                        return []

        tasks = [_fetch_for_dest(d) for d in target_destinations]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_offers: List[FlightOffer] = []
        for res in results_list:
            if isinstance(res, list):
                all_offers.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"[PROVIDER_ERR] Task exception during gather for {origin} -> {destination}: {res}")

        if not all_offers:
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            logger.info(f"[PROVIDER] Finished search {origin} -> {destination} in {elapsed_ms:.1f}ms: 0 offers found.")
            return []

        # Deduplicate offers by (price, airline, origin, destination)
        unique_offers: List[FlightOffer] = []
        seen = set()
        for offer in all_offers:
            key = (offer.price, offer.airline, offer.origin, offer.destination)
            if key not in seen:
                seen.add(key)
                unique_offers.append(offer)

        if direct_only:
            unique_offers = [o for o in unique_offers if o.is_direct]

        unique_offers.sort(key=lambda x: x.price)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        if unique_offers:
            logger.info(f"[PROVIDER] Finished search {origin} -> {destination} in {elapsed_ms:.1f}ms: {len(unique_offers)} unique offers found (lowest €{unique_offers[0].price:.2f}).")
        else:
            logger.info(f"[PROVIDER] Finished search {origin} -> {destination} in {elapsed_ms:.1f}ms: 0 unique offers found.")
        return unique_offers

    async def search_flights_range(
        self,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        currency: str = "EUR",
        direct_only: bool = False,
        max_days: Optional[int] = 60
    ) -> List[FlightOffer]:
        from utils.date_parser import generate_date_sequence
        dates = generate_date_sequence(start_date, end_date, max_days=max_days)
        logger.info(f"[PROVIDER] Starting range search: {origin} -> {destination} across {len(dates)} dates ({start_date} to {end_date})")

        t_start = time.perf_counter()
        tasks = [
            self.search_flights(
                origin=origin,
                destination=destination,
                departure_date=d,
                currency=currency,
                direct_only=direct_only
            )
            for d in dates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_offers: List[FlightOffer] = []
        for res in results:
            if isinstance(res, list):
                all_offers.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"[PROVIDER_ERR] Error fetching flight range date: {res}")

        all_offers.sort(key=lambda x: x.price)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        logger.info(f"[PROVIDER] Finished range search {origin} -> {destination} in {elapsed_ms:.1f}ms: {len(all_offers)} offers found total.")
        return all_offers


