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
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))



class AbstractFlightProvider(ABC):
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

