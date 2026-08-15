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
    """Calculate discount percentage relative to Google Flights typical price baseline.
    Positive values indicate discounts (+28.0 = 28% below average / 28% OFF).
    Negative values indicate expensive flights (-49.0 = 49% above average).
    """
    if baseline_min is not None and baseline_max is not None and (baseline_min + baseline_max) > 0:
        baseline = (baseline_min + baseline_max) / 2.0
    elif baseline_min is not None and baseline_min > 0:
        baseline = baseline_min
    elif baseline_max is not None and baseline_max > 0:
        baseline = baseline_max
    else:
        return 0.0

    discount = ((baseline - current_price) / baseline) * 100.0
    return round(discount, 1)

def _filter_and_cap_deals(all_deals: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
    seen_destinations = set()
    unique_deals = []
    for deal in all_deals:
        dst = deal["destination_code"]
        if dst in seen_destinations:
            continue
        seen_destinations.add(dst)
        unique_deals.append(deal)

    country_counts: Dict[str, int] = {}
    capped_deals: List[Dict[str, Any]] = []
    for deal in unique_deals:
        c = deal["country"]
        if c:
            current_count = country_counts.get(c, 0)
            if current_count >= 2:
                continue
            country_counts[c] = current_count + 1
        capped_deals.append(deal)

    return capped_deals[:max_results]

async def run_explore_query(
    origin: str,
    region: str,
    departure_date: str,
    max_budget: Optional[float] = None,
    sort_by: str = "discount",
    max_results: int = 10
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Query primary country airports in a region and score deal opportunities."""
    airports = get_region_airports(region)
    if not airports:
        logger.warning(f"No airports registered for region: {region}")
        return {} if sort_by == "both" else []

    origin_country = get_airport_country(origin)
    normalized_region = region.lower().strip()
    provider = FastFlightsProvider()

    logger.info(f"🔍 Starting /explore query: {origin} -> {region} ({departure_date}), checking {len(airports)} airports...")

    async def fetch_airport_deals(target_airport: Dict[str, str]) -> List[Dict[str, Any]]:
        dst_code = target_airport["code"]
        dst_name = target_airport.get("name", dst_code)
        country = target_airport.get("country", "")

        if dst_code.upper() == origin.upper():
            return []

        if normalized_region != "islands" and origin_country:
            o_c = origin_country.strip().lower()
            d_c = country.strip().lower()
            if o_c == d_c:
                return []
            if o_c == "greece" and d_c == "cyprus":
                return []

        try:
            if ".." in departure_date:
                s_d, e_d = departure_date.split("..", 1)
                offers = await asyncio.wait_for(
                    provider.search_flights_range(origin, dst_code, s_d, e_d, currency="EUR", max_days=3),
                    timeout=30.0
                )
            else:
                offers = await asyncio.wait_for(
                    provider.search_flights(origin, dst_code, departure_date, currency="EUR"),
                    timeout=20.0
                )

            if not offers:
                logger.info(f"ℹ️ {origin} -> {dst_code}: no offers found.")
                return []

            logger.info(f"✅ {origin} -> {dst_code}: found {len(offers)} flight offers.")
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

                flight_date = getattr(offer, "departure_date", None) or departure_date
                results.append({
                    "origin_code": origin,
                    "destination_code": dst_code,
                    "destination_name": dst_name,
                    "country": country,
                    "departure_date": flight_date,
                    "price": price,
                    "airline": airline,
                    "baseline_price": baseline_price,
                    "discount_pct": discount_pct
                })
            return results
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout fetching flights for {origin} -> {dst_code}")
            return []
        except Exception as e:
            logger.warning(f"❌ Failed to query {origin} -> {dst_code}: {e}")
            return []

    # Parallel query execution across airports
    raw_results_nested = await asyncio.gather(*[fetch_airport_deals(a) for a in airports])
    all_deals = [deal for sublist in raw_results_nested for deal in sublist]
    logger.info(f"🎉 /explore query complete! Total valid deals across {region}: {len(all_deals)}")

    if not all_deals:
        return {} if sort_by == "both" else []

    # Sorting and capping
    if sort_by == "both":
        deals_discount = list(all_deals)
        deals_discount.sort(key=lambda x: (-x["discount_pct"], x["price"]))
        capped_discount = _filter_and_cap_deals(deals_discount, max_results)

        deals_price = list(all_deals)
        deals_price.sort(key=lambda x: x["price"])
        capped_price = _filter_and_cap_deals(deals_price, max_results)

        return {
            "discount_deals": capped_discount,
            "cheapest_deals": capped_price
        }

    if sort_by == "price":
        all_deals.sort(key=lambda x: x["price"])
    else:
        all_deals.sort(key=lambda x: (-x["discount_pct"], x["price"]))

    return _filter_and_cap_deals(all_deals, max_results)
