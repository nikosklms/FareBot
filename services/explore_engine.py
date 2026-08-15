import asyncio
import logging
import time
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

def _filter_and_cap_deals(all_deals: List[Dict[str, Any]], max_results: int, allow_same_country: bool = False) -> List[Dict[str, Any]]:
    seen_destinations = set()
    unique_deals = []
    for deal in all_deals:
        dst = deal["destination_code"]
        if dst in seen_destinations:
            continue
        seen_destinations.add(dst)
        unique_deals.append(deal)

    if allow_same_country:
        return unique_deals[:max_results]

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
        logger.warning(f"[EXPLORE] No airports registered for region: '{region}'")
        return {} if sort_by == "both" else []

    t_start = time.perf_counter()
    logger.info(f"[EXPLORE] 🔍 Starting /explore query: origin={origin}, region={region}, date={departure_date}, max_budget={max_budget}, sort_by={sort_by}, max_results={max_results} ({len(airports)} airports registered)")

    origin_country = get_airport_country(origin)
    normalized_region = region.lower().strip()
    provider = FastFlightsProvider()

    from utils.date_parser import parse_date_or_range
    start_date, end_date = parse_date_or_range(departure_date)

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
            if end_date:
                offers = await provider.search_flights_range(origin, dst_code, start_date, end_date, currency="EUR")
            else:
                offers = await provider.search_flights(origin, dst_code, departure_date, currency="EUR")

            if not offers:
                logger.debug(f"[EXPLORE] {origin} -> {dst_code}: 0 flight offers returned")
                return []

            results = []
            for offer in offers:
                price = getattr(offer, "price", None)
                if price is None or (max_budget is not None and max_budget > 0 and price > max_budget):
                    continue

                airline = getattr(offer, "airline", "Unknown")
                typ_min = getattr(offer, "typical_min", None)
                typ_max = getattr(offer, "typical_max", None)
                discount_pct = calculate_discount_score(price, typ_min, typ_max)

                baseline_price = ((typ_min + typ_max) / 2.0) if (typ_min and typ_max) else None
                offer_dep_date = getattr(offer, "departure_date", departure_date)

                results.append({
                    "origin_code": origin,
                    "destination_code": dst_code,
                    "destination_name": dst_name,
                    "country": country,
                    "departure_date": offer_dep_date,
                    "price": price,
                    "airline": airline,
                    "baseline_price": baseline_price,
                    "discount_pct": discount_pct,
                    "is_direct": getattr(offer, "is_direct", True)
                })
            if results:
                logger.info(f"[EXPLORE] ✅ {origin} -> {dst_code} ({country}): found {len(results)} flight offers within criteria (lowest €{results[0]['price']:.2f}).")
            else:
                logger.info(f"[EXPLORE] ℹ️ {origin} -> {dst_code} ({country}): 0 flight offers matching criteria.")
            return results
        except Exception as e:
            logger.error(f"[EXPLORE_ERR] Failed to query {origin} -> {dst_code}: {e}")
            return []

    # Parallel query execution across airports
    raw_results_nested = await asyncio.gather(*[fetch_airport_deals(a) for a in airports])
    all_deals = [deal for sublist in raw_results_nested for deal in sublist]

    elapsed_s = time.perf_counter() - t_start

    if not all_deals:
        logger.warning(f"[EXPLORE] Completed explore query in {elapsed_s:.2f}s: 0 matching deals found across {len(airports)} airports.")
        return {} if sort_by == "both" else []

    logger.info(f"[EXPLORE] Completed query in {elapsed_s:.2f}s: Found {len(all_deals)} total candidate deals across {len(airports)} airports.")

    allow_same_country = (normalized_region == "islands")

    # Sorting and capping
    if sort_by == "both":
        deals_discount = list(all_deals)
        deals_discount.sort(key=lambda x: (-x["discount_pct"], x["price"]))
        capped_discount = _filter_and_cap_deals(deals_discount, max_results, allow_same_country=allow_same_country)

        deals_price = list(all_deals)
        deals_price.sort(key=lambda x: x["price"])
        capped_price = _filter_and_cap_deals(deals_price, max_results, allow_same_country=allow_same_country)

        logger.info(f"[EXPLORE] Capped deals: {len(capped_discount)} discount deals, {len(capped_price)} cheapest deals.")
        return {
            "discount_deals": capped_discount,
            "cheapest_deals": capped_price
        }

    if sort_by == "price":
        all_deals.sort(key=lambda x: x["price"])
    else:
        all_deals.sort(key=lambda x: (-x["discount_pct"], x["price"]))

    final_deals = _filter_and_cap_deals(all_deals, max_results, allow_same_country=allow_same_country)
    logger.info(f"[EXPLORE] Final output: {len(final_deals)} deals selected for user display.")
    return final_deals

