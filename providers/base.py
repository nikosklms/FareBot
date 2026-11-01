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


@dataclass
class ProviderStats:
    """Counts since the bot started, for /stats."""
    searches: int = 0
    from_cache: int = 0          # answered from a result less than 15 minutes old
    shared: int = 0              # joined an identical search that was already running
    google_requests: int = 0
    rate_limit_pauses: int = 0
    paused_for: float = 0.0      # seconds left in the current rate-limit pause
    average_latency: float = 0.0


class FlightSearchError(Exception):
    """Google Flights couldn't be searched (rate limiting, network or server errors).

    Distinct from an empty result, which means the search worked and found no flights.
    """


class PartialSearchError(FlightSearchError):
    """Some days of a date range couldn't be searched. offers holds what the other days found,
    sorted by price, so a price under budget is still real, but the lowest price may not be.
    """

    def __init__(self, offers: list, failed_days: int, total_days: int) -> None:
        super().__init__(f"{failed_days} of {total_days} days couldn't be searched")
        self.offers = offers


class AbstractFlightProvider(ABC):
    # Requests the provider runs in parallel, used for time estimates.
    concurrency: int = 1

    def average_latency(self) -> float:
        """Average seconds per query, used for time estimates."""
        return 1.0

    def stats(self) -> ProviderStats:
        return ProviderStats()

    def seconds_left(self, upcoming: int = 0) -> Optional[float]:
        """Estimated seconds until the current job's searches are done, counting the other jobs
        sharing the request slots; None when the provider can't tell. `upcoming` counts searches
        the job is about to start."""
        return None

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

