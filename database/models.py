from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

ACTIVE = "ACTIVE"
PAUSED = "PAUSED"
EXPIRED = "EXPIRED"

# Access requests (users table); ALLOWED_USERS in .env always has access.
PENDING = "PENDING"
APPROVED = "APPROVED"
DENIED = "DENIED"

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SORT_MODES = ("discount", "price", "both")


@dataclass
class Tracker:
    """A single route watched for a price drop below max_budget."""
    id: int
    user_id: int
    origin_code: str
    destination_code: str
    departure_date: str
    departure_date_end: Optional[str]
    max_budget: float
    frequency_hours: int
    direct_only: bool
    status: str
    consecutive_failures: int = 0
    last_checked_at: Optional[str] = None
    last_price_found: Optional[float] = None
    created_at: Optional[str] = None

    @property
    def last_departure_date(self) -> str:
        return self.departure_date_end or self.departure_date


@dataclass
class Digest:
    """A weekly regional deal report.

    The departure window is either rolling (days_ahead from delivery day)
    or fixed (departure_date, optionally through departure_date_end).
    """
    id: int
    user_id: int
    origin_code: str
    region: str
    max_budget: Optional[float]
    days_ahead: Optional[int]
    departure_date: Optional[str]
    departure_date_end: Optional[str]
    sort_mode: str
    delivery_day: str
    delivery_time: str
    max_results: int
    status: str
    direct_only: bool = False
    created_at: Optional[str] = None

    def window(self, today: date) -> tuple[str, Optional[str]]:
        """Departure window to query on a given day."""
        if self.days_ahead is not None:
            start = today + timedelta(days=1)
            end = today + timedelta(days=self.days_ahead)
            return start.isoformat(), end.isoformat()
        return self.departure_date, self.departure_date_end


@dataclass
class User:
    """Someone who asked to use the bot, and what the admin decided."""
    user_id: int
    username: Optional[str]
    full_name: Optional[str]
    status: str
    requested_at: Optional[str] = None
    decided_at: Optional[str] = None
