import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from providers.base import AbstractFlightProvider
from services.airports_data import get_airport_country, get_region_airports
from services.progress import Progress
from utils.date_parser import generate_date_sequence

logger = logging.getLogger(__name__)

MAX_PER_COUNTRY = 2

# (queries done, total queries, estimated seconds left, airports, days)
ProgressCallback = Callable[[int, int, float, int, int], Awaitable[None]]


@dataclass
class Deal:
    origin: str
    destination: str
    destination_name: str
    country: str
    departure_date: str
    price: float
    airline: str
    is_direct: bool
    baseline_price: Optional[float]
    discount_pct: float


@dataclass
class DealSection:
    """One ranked list of deals; sort_mode is 'discount' or 'price'."""
    sort_mode: str
    deals: list[Deal]


def baseline_price(typical_min: Optional[float], typical_max: Optional[float]) -> Optional[float]:
    """Google's typical price: the middle of its range, or whichever end is known."""
    if typical_min and typical_max:
        return (typical_min + typical_max) / 2.0
    return typical_min or typical_max or None


def calculate_discount_score(
    current_price: float,
    baseline_min: Optional[float] = None,
    baseline_max: Optional[float] = None,
) -> float:
    """Percent below Google's typical price (positive = cheaper than usual)."""
    baseline = baseline_price(baseline_min, baseline_max)
    if not baseline:
        return 0.0
    return round((baseline - current_price) / baseline * 100.0, 1)


def _skip_destination(origin: str, origin_country: Optional[str], airport: dict, region: str) -> bool:
    if airport["code"] == origin:
        return True
    if region == "islands" or not origin_country:
        return False
    origin_c = origin_country.lower()
    dest_c = airport.get("country", "").lower()
    return origin_c == dest_c or (origin_c == "greece" and dest_c == "cyprus")


async def find_deals(
    provider: AbstractFlightProvider,
    origin: str,
    region: str,
    start_date: str,
    end_date: Optional[str] = None,
    max_budget: Optional[float] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> list[Deal]:
    """Query every airport in a region for every date in the window."""
    origin = origin.upper()
    region = region.lower().strip()
    origin_country = get_airport_country(origin)
    airports = [a for a in get_region_airports(region) if not _skip_destination(origin, origin_country, a, region)]
    if not airports:
        logger.warning("[EXPLORE] No airports to query for region '%s'", region)
        return []

    dates = generate_date_sequence(start_date, end_date) if end_date else [start_date]
    total = len(airports) * len(dates)
    logger.info("[EXPLORE] %s -> %s: %d airports x %d days = %d queries", origin, region, len(airports), len(dates), total)

    t_start = time.perf_counter()

    async def report(done: int, total_queries: int, seconds_left: float) -> None:
        if on_progress:
            await on_progress(done, total_queries, seconds_left, len(airports), len(dates))

    progress = Progress(total, report, provider.average_latency() / provider.concurrency)
    await progress.start()

    async def fetch(code: str, departure_date: str) -> list:
        try:
            return await provider.search_flights(origin, code, departure_date)
        except Exception:
            logger.exception("[EXPLORE] Query failed: %s -> %s on %s", origin, code, departure_date)
            return []

    async def query(airport: dict, departure_date: str) -> list[Deal]:
        offers = await progress.track(fetch(airport["code"], departure_date))
        deals = []
        for offer in offers:
            if max_budget and offer.price > max_budget:
                continue
            deals.append(Deal(
                origin=origin,
                destination=airport["code"],
                destination_name=airport.get("name", airport["code"]),
                country=airport.get("country", ""),
                departure_date=offer.departure_date,
                price=offer.price,
                airline=offer.airline or "Various",
                is_direct=offer.is_direct,
                baseline_price=baseline_price(offer.typical_min, offer.typical_max),
                discount_pct=calculate_discount_score(offer.price, offer.typical_min, offer.typical_max),
            ))
        return deals

    results = await asyncio.gather(*(query(a, d) for a in airports for d in dates))
    deals = [deal for batch in results for deal in batch]
    logger.info("[EXPLORE] %s -> %s finished in %.1fs: %d candidate deals",
                origin, region, time.perf_counter() - t_start, len(deals))
    return deals


def _one_per_destination(deals: list[Deal], limit: int, cap_per_country: bool) -> list[Deal]:
    seen: set[str] = set()
    per_country: dict[str, int] = {}
    picked = []
    for deal in deals:
        if deal.destination in seen:
            continue
        if cap_per_country and deal.country and per_country.get(deal.country, 0) >= MAX_PER_COUNTRY:
            continue
        seen.add(deal.destination)
        per_country[deal.country] = per_country.get(deal.country, 0) + 1
        picked.append(deal)
        if len(picked) == limit:
            break
    return picked


def rank_deals(deals: list[Deal], sort_mode: str, limit: int, region: str) -> list[DealSection]:
    """Best deal per destination, at most two per country (except Greek islands)."""
    cap_per_country = region.lower() != "islands"
    modes = ["discount", "price"] if sort_mode == "both" else [sort_mode]
    sections = []
    for mode in modes:
        if mode == "price":
            ordered = sorted(deals, key=lambda d: d.price)
        else:
            ordered = sorted(deals, key=lambda d: (-d.discount_pct, d.price))
        picked = _one_per_destination(ordered, limit, cap_per_country)
        if picked:
            sections.append(DealSection(mode, picked))
    return sections
