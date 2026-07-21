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

def parse_google_flights_payload(html: str, default_origin: str, default_destination: str, departure_date: str, return_date: Optional[str], currency: str) -> List[FlightOffer]:
    """Parse both payload[2] (Top/Best Flights) and payload[3] (Other Flights) from Google Flights HTML."""
    offers: List[FlightOffer] = []
    try:
        parser = LexborHTMLParser(html)
        script = parser.css_first(r"script.ds\:1")
        if not script:
            return offers

        js = script.text()
        data_str = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data_str)
    except Exception as e:
        logger.warning(f"Failed to parse script.ds:1 JSON payload: {e}")
        return offers

    def unwrap_item(item):
        while isinstance(item, list) and len(item) == 1 and isinstance(item[0], list):
            item = item[0]
        return item

    def process_flight_list(flight_list):
        if not flight_list or not isinstance(flight_list, list):
            return

        for raw_item in flight_list:
            try:
                item = unwrap_item(raw_item)
                if not isinstance(item, list) or len(item) == 0:
                    continue

                flight_info = None
                price_val = None

                for elem in item:
                    if isinstance(elem, list):
                        if len(elem) >= 3 and isinstance(elem[1], list) and isinstance(elem[2], list):
                            flight_info = elem
                        if len(elem) >= 1 and isinstance(elem[0], list) and len(elem[0]) >= 2:
                            if elem[0][0] is None and isinstance(elem[0][1], (int, float)):
                                price_val = float(elem[0][1])

                if flight_info and price_val is not None and price_val > 0:
                    airlines = flight_info[1] if isinstance(flight_info[1], list) else ["Various Airlines"]
                    airline_name = ", ".join(airlines) if airlines else "Various Airlines"
                    legs = flight_info[2] if isinstance(flight_info[2], list) else []
                    orig = legs[0][3] if legs and len(legs[0]) > 3 else default_origin
                    dest = legs[-1][6] if legs and len(legs[-1]) > 6 else default_destination

                    offers.append(
                        FlightOffer(
                            origin=orig,
                            destination=dest,
                            departure_date=departure_date,
                            return_date=return_date,
                            price=price_val,
                            currency=currency,
                            airline=airline_name,
                            booking_url=f"https://www.google.com/travel/flights?q=Flights%20to%20{dest}%20from%20{orig}%20on%20{departure_date}"
                        )
                    )
            except Exception:
                continue

    # Parse payload[2] (Top / Best Flights - includes low-cost carriers like Ryanair/easyJet)
    if len(payload) > 2 and isinstance(payload[2], list):
        process_flight_list(payload[2])

    # Parse payload[3] (Other Flights)
    if len(payload) > 3 and isinstance(payload[3], list):
        for sub in payload[3]:
            if isinstance(sub, list):
                process_flight_list(sub)

    return offers

class FastFlightsProvider(AbstractFlightProvider):
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR"
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

                q = create_query(
                    flights=flight_queries,
                    trip="round-trip" if return_date else "one-way",
                    passengers=Passengers(adults=1),
                    currency=currency
                )

                try:
                    html = await loop.run_in_executor(None, lambda: fetcher.fetch_html(q))
                    return parse_google_flights_payload(html, origin, dest_code, departure_date, return_date, currency)
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

        # Sort strictly ascending by price so lowest price option is ALWAYS #1
        unique_offers.sort(key=lambda x: x.price)
        return unique_offers
