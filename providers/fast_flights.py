import logging
import asyncio
import urllib.request
import urllib.parse
from typing import List, Optional
from fast_flights import get_flights, create_query, FlightQuery, Passengers
from fast_flights.integrations.base import FetchIntegration
from providers.base import AbstractFlightProvider, FlightOffer

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

        flight_queries = [FlightQuery(date=departure_date, from_airport=origin, to_airport=destination)]
        if return_date:
            flight_queries.append(FlightQuery(date=return_date, from_airport=destination, to_airport=origin))

        q = create_query(
            flights=flight_queries,
            trip="round-trip" if return_date else "one-way",
            passengers=Passengers(adults=1),
            currency=currency
        )

        def _fetch():
            return get_flights(q, integration=UrllibFetchIntegration())

        try:
            res = await loop.run_in_executor(None, _fetch)
        except Exception as e:
            logger.error(f"Error fetching flight offers for {origin} -> {destination} on {departure_date}: {e}", exc_info=True)
            return []

        offers: List[FlightOffer] = []
        if not res:
            return offers

        for item in res:
            try:
                price_val = getattr(item, "price", 0)
                price_clean = float("".join(c for c in str(price_val) if c.isdigit() or c == "."))
                
                airlines_list = getattr(item, "airlines", [])
                airline_name = ", ".join(airlines_list) if airlines_list else "Various Airlines"

                offers.append(
                    FlightOffer(
                        origin=origin,
                        destination=destination,
                        departure_date=departure_date,
                        return_date=return_date,
                        price=price_clean,
                        currency=currency,
                        airline=airline_name,
                        booking_url=f"https://www.google.com/travel/flights?q=Flights%20to%20{destination}%20from%20{origin}%20on%20{departure_date}"
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing flight offer item: {e}")
                continue

        return offers
