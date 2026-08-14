import asyncio
import logging
from typing import List, Dict, Any, Optional
from providers.fast_flights import FastFlightsProvider
from services.airports_data import get_region_airports, get_airport_country

logger = logging.getLogger(__name__)

def calculate_discount_score(
    current_price: float,
    baseline_min: Optional[float] = None,
    baseline_max: Optional[float] = None
) -> float:
    """Calculate discount percentage relative to Google Flights typical price baseline."""
    if baseline_min is not None and baseline_max is not None and (baseline_min + baseline_max) > 0:
        baseline = (baseline_min + baseline_max) / 2.0
    elif baseline_min is not None and baseline_min > 0:
        baseline = baseline_min
    elif baseline_max is not None and baseline_max > 0:
        baseline = baseline_max
    else:
        return 0.0

    if current_price >= baseline:
        return 0.0

    discount = ((baseline - current_price) / baseline) * 100.0
    return round(discount, 2)

async def run_explore_query(
    origin: str,
    region: str,
    departure_date: str,
    max_budget: Optional[float] = None,
    sort_by: str = "discount"
) -> List[Dict[str, Any]]:
    """Query primary country airports in a region and score deal opportunities."""
    airports = get_region_airports(region)
    if not airports:
        logger.warning(f"No airports registered for region: {region}")
        return []

    origin_country = get_airport_country(origin)
    normalized_region = region.lower().strip()
    provider = FastFlightsProvider()

    async def fetch_airport_deals(target_airport: Dict[str, str]) -> List[Dict[str, Any]]:
        dst_code = target_airport["code"]
        dst_name = target_airport.get("name", dst_code)
        country = target_airport.get("country", "")

        if dst_code.upper() == origin.upper():
            return []

        if normalized_region != "islands" and origin_country and country.strip().lower() == origin_country.strip().lower():
            return []

        try:
            offers = await provider.search_flights(origin, dst_code, departure_date, currency="EUR")
            if not offers:
                return []

            results = []
            for offer in offers:
                price = getattr(offer, "price", None)
                if price is None or (max_budget is not None and price > max_budget):
                    continue

                airline = getattr(offer, "airline", "Unknown")
                typ_min = getattr(offer, "typical_min", None)
                typ_max = getattr(offer, "typical_max", None)
                discount_pct = calculate_discount_score(price, typ_min, typ_max)

                baseline_price = ((typ_min + typ_max) / 2.0) if (typ_min and typ_max) else None

                results.append({
                    "origin_code": origin,
                    "destination_code": dst_code,
                    "destination_name": dst_name,
                    "country": country,
                    "departure_date": departure_date,
                    "price": price,
                    "airline": airline,
                    "baseline_price": baseline_price,
                    "discount_pct": discount_pct
                })
            return results
        except Exception as e:
            logger.debug(f"Failed to query {origin} -> {dst_code}: {e}")
            return []

    # Parallel query execution across airports
    raw_results_nested = await asyncio.gather(*[fetch_airport_deals(a) for a in airports])
    all_deals = [deal for sublist in raw_results_nested for deal in sublist]

    if not all_deals:
        return []

    # Sorting
    if sort_by == "price":
        all_deals.sort(key=lambda x: x["price"])
    else:
        all_deals.sort(key=lambda x: x["discount_pct"], reverse=True)

    # Regional Diversity Cap (Max 2 per country)
    country_counts: Dict[str, int] = {}
    capped_deals: List[Dict[str, Any]] = []

    for deal in all_deals:
        c = deal["country"]
        if c:
            current_count = country_counts.get(c, 0)
            if current_count >= 2:
                continue
            country_counts[c] = current_count + 1
        capped_deals.append(deal)

    return capped_deals
