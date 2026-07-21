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
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class AbstractFlightProvider(ABC):
    @abstractmethod
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR"
    ) -> List[FlightOffer]:
        """Fetch matching flight offers for the given criteria."""
        pass
