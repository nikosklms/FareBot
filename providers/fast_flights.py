import logging
import asyncio
import urllib.request
import urllib.parse
import json
from typing import List, Optional
from selectolax.lexbor import LexborHTMLParser
from fast_flights import create_query, FlightQuery, Passengers
from fast_flights.integrations.base import FetchIntegration
from providers.base import AbstractFlightProvider, FlightOffer
from services.airports_data import MULTI_AIRPORT_CITIES

logger = logging.getLogger(__name__)

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
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.read().decode("utf-8")

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

def parse_google_flights_payload_generic(
    html: str,
    default_origin: str,
    default_destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    currency: str = "EUR"
) -> List[FlightOffer]:
    """Parse Google Flights html JSON payload and extract matching flight offers."""
    offers: List[FlightOffer] = []
    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if not script:
        return offers

    try:
        js = script.text()
        data_str = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data_str)
    except Exception as e:
        logger.warning(f"Failed to parse script.ds:1 JSON payload: {e}")
        return offers

    def _walk(obj):
        if not isinstance(obj, list):
            return

        flight_info = None
        price_val = None
        token_str = None

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

                if len(elem) > 1 and isinstance(elem[1], str) and elem[1].startswith("Cj"):
                    token_str = elem[1]
                elif len(elem) > 0 and isinstance(elem[0], list) and len(elem[0]) > 1 and isinstance(elem[0][1], str) and elem[0][1].startswith("Cj"):
                    token_str = elem[0][1]

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

            if token_str and token_str.startswith("Cj"):
                booking_url_val = f"https://www.google.com/travel/flights/search?tfs={urllib.parse.quote(token_str)}&curr={currency}"
            else:
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
        sem = asyncio.Semaphore(2)  # Limit concurrent HTTP requests to prevent Google rate limits

        async def _fetch_for_dest(dest_code: str) -> List[FlightOffer]:
            async with sem:
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


                try:
                    html = await loop.run_in_executor(None, lambda: fetcher.fetch_html(q))
                    return parse_google_flights_payload_generic(html, origin, dest_code, departure_date, return_date, currency)
                except Exception as e:
                    logger.error(f"Error fetching flights for {origin} -> {dest_code} on {departure_date}: {e}")
                    return []


        tasks = [_fetch_for_dest(d) for d in target_destinations]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_offers: List[FlightOffer] = []
        for res in results_list:
            if isinstance(res, list):
                all_offers.extend(res)

        if not all_offers:
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

        # Sort strictly ascending by numerical float price so lowest price option is ALWAYS #1
        unique_offers.sort(key=lambda x: x.price)
        return unique_offers

