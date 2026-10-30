from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

@dataclass
class FlightOffer:
    origin: str
    destination: str
    departure_date: str
    price: float
    currency: str = "EUR"
    return_date: Optional[str] = None
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    booking_url: Optional[str] = None
    is_direct: bool = True
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    day_offset: int = 0
    typical_min: Optional[float] = None
    typical_max: Optional[float] = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FlightSearchError(Exception):
    """Google Flights couldn't be searched (rate limiting, network or server errors).

    Distinct from an empty result, which means the search worked and found no flights.
    """


class AbstractFlightProvider(ABC):
    # Requests the provider runs in parallel, used for time estimates.
    concurrency: int = 1

    def average_latency(self) -> float:
        """Average seconds per query, used for time estimates."""
        return 1.0

    async def close(self) -> None:  # noqa: B027 - optional hook, most providers have nothing to release
        """Release network resources when the bot stops."""

    @abstractmethod
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        """Fetch matching flight offers for the given criteria."""
        pass

    @abstractmethod
    async def search_flights_range(
        self,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        """Fetch flight offers across a range of departure dates."""
        pass

