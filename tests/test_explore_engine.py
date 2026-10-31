from providers.base import FlightOffer
from services.explore_engine import Deal, baseline_price, calculate_discount_score, find_deals, rank_deals
from tests.fakes import FakeProvider


def offers_by_destination(prices):
    """prices: {destination: (price, typical_min, typical_max)}"""
    def offers(origin, destination, day):
        if destination not in prices:
            return []
        price, low, high = prices[destination]
        return [FlightOffer(origin, destination, day, price=price, airline="Air", typical_min=low, typical_max=high)]
    return offers


def deal(destination, price, discount, country="X"):
    return Deal("ATH", destination, destination, country, "2027-01-01", price, "Air", True, None, discount)


def test_discount_score():
    assert calculate_discount_score(50.0, 190.0, 210.0) == 75.0
    assert calculate_discount_score(220.0, 190.0, 210.0) == -10.0
    assert calculate_discount_score(50.0, None, 100.0) == 50.0
    assert calculate_discount_score(50.0) == 0.0


def test_baseline_price():
    assert baseline_price(80.0, 120.0) == 100.0
    assert baseline_price(80.0, None) == 80.0
    assert baseline_price(None, None) is None


async def test_unknown_region_returns_nothing():
    provider = FakeProvider()
    assert (await find_deals(provider, "ATH", "atlantis", "2027-01-01")).deals == []
    assert provider.queries == []


async def test_skips_origin_country_and_cyprus_for_greek_origins():
    provider = FakeProvider(offers_by_destination({"SKG": (30, 80, 100), "LCA": (35, 80, 100), "FCO": (40, 90, 110)}))
    deals = (await find_deals(provider, "ATH", "europe", "2027-01-01")).deals

    assert [d.destination for d in deals] == ["FCO"]
    queried = {destination for _, destination, _, _ in provider.queries}
    assert "SKG" not in queried and "LCA" not in queried and "ATH" not in queried


async def test_islands_keep_same_country_destinations():
    provider = FakeProvider(offers_by_destination({"JTR": (30, 80, 100)}))
    deals = (await find_deals(provider, "ATH", "islands", "2027-01-01")).deals
    assert [d.destination for d in deals] == ["JTR"]


async def test_queries_every_day_of_a_range_and_applies_budget():
    provider = FakeProvider(offers_by_destination({"FCO": (40, 90, 110), "MAD": (140, 90, 110)}))
    deals = (await find_deals(provider, "ATH", "europe", "2027-01-01", "2027-01-03", max_budget=100)).deals

    assert {d.departure_date for d in deals} == {"2027-01-01", "2027-01-02", "2027-01-03"}
    assert {d.destination for d in deals} == {"FCO"}
    assert len([q for q in provider.queries if q[1] == "FCO"]) == 3


async def test_provider_errors_do_not_stop_other_airports():
    def offers(origin, destination, day):
        if destination == "CDG":
            raise RuntimeError("timeout")
        return offers_by_destination({"FCO": (40, 90, 110)})(origin, destination, day)

    search = await find_deals(FakeProvider(offers), "ATH", "europe", "2027-01-01")
    assert [d.destination for d in search.deals] == ["FCO"]
    assert search.failed_queries == 1 and not search.all_failed


async def test_reports_progress():
    updates = []

    async def progress(done, total, seconds, airports, days):
        updates.append((done, total, airports, days))

    await find_deals(FakeProvider(), "ATH", "oceania", "2027-01-01", "2027-01-02", on_progress=progress)
    airports = len(__import__("services.airports_data", fromlist=["x"]).get_region_airports("oceania"))
    assert updates[0] == (0, airports * 2, airports, 2)


def test_rank_by_discount_caps_two_per_country_and_breaks_ties_by_price():
    deals = [
        deal("CDG", 50, 75, "France"), deal("ORY", 45, 70, "France"), deal("NCE", 40, 50, "France"),
        deal("FCO", 40, 60, "Italy"), deal("ZAG", 44, 0, "Croatia"), deal("SJJ", 46, 0, "Bosnia"),
    ]
    [section] = rank_deals(deals, "discount", 10, "europe")
    assert section.sort_mode == "discount"
    assert [d.destination for d in section.deals] == ["CDG", "ORY", "FCO", "ZAG", "SJJ"]


def test_rank_keeps_best_offer_per_destination_and_respects_limit():
    deals = [deal("CDG", 90, 10), deal("CDG", 60, 40), deal("FCO", 70, 30), deal("MAD", 20, 5)]
    [section] = rank_deals(deals, "price", 2, "europe")
    assert [(d.destination, d.price) for d in section.deals] == [("MAD", 20), ("CDG", 60)]


def test_rank_both_returns_two_sections_and_skips_empty():
    deals = [deal("CDG", 100, 50, "France"), deal("SOF", 20, 0, "Bulgaria")]
    sections = rank_deals(deals, "both", 10, "europe")
    assert [s.sort_mode for s in sections] == ["discount", "price"]
    assert sections[0].deals[0].destination == "CDG"
    assert sections[1].deals[0].destination == "SOF"
    assert rank_deals([], "both", 10, "europe") == []


def test_islands_have_no_country_cap():
    deals = [deal(code, 30 + i, 10, "Greece") for i, code in enumerate(["JTR", "JMK", "RHO"])]
    [section] = rank_deals(deals, "price", 10, "islands")
    assert len(section.deals) == 3


async def test_airports_covered_by_another_are_searched_once():
    from services.explore_engine import find_deals
    from tests.fakes import FakeProvider, future
    provider = FakeProvider()
    await find_deals(provider, "ATH", "middle_east", future(1))
    destinations = [destination for _, destination, _, _ in provider.queries]
    assert "IST" in destinations and "SAW" not in destinations  # IST already searches SAW
