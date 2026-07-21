import asyncio
from typing import List, Optional
from fast_flights import get_flights, FlightQuery, Passengers
from providers.base import AbstractFlightProvider, FlightOffer

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

        flight_data = [FlightQuery(date=departure_date, from_airport=origin, to_airport=destination)]
        if return_date:
            flight_data.append(FlightQuery(date=return_date, from_airport=destination, to_airport=origin))

        def _fetch():
            return get_flights(
                flight_data=flight_data,
                trip="round-trip" if return_date else "one-way",
                passengers=Passengers(adults=1),
                currency=currency
            )

        try:
            res = await loop.run_in_executor(None, _fetch)
        except Exception:
            return []

        offers: List[FlightOffer] = []
        if not res or not hasattr(res, "flights") or not res.flights:
            return offers

        for item in res.flights:
            try:
                price_str = getattr(item, "price", "0")
                price_clean = float("".join(c for c in str(price_str) if c.isdigit() or c == "."))
                airline_name = getattr(item, "name", "Unknown Airline")

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
            except Exception:
                continue

        return offers
