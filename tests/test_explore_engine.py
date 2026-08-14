import pytest
from unittest.mock import AsyncMock, patch
from services.explore_engine import run_explore_query, calculate_discount_score

def test_calculate_discount_score():
    # Baseline 200 EUR, price 50 EUR -> (200-50)/200 = 75.0% discount
    score = calculate_discount_score(current_price=50.0, baseline_min=190.0, baseline_max=210.0)
    assert abs(score - 75.0) < 0.1

def test_discount_score_zero_when_price_above_baseline():
    # Current price 220 EUR, baseline 200 EUR -> 0% discount
    score = calculate_discount_score(current_price=220.0, baseline_min=190.0, baseline_max=210.0)
    assert score == 0.0

@pytest.mark.asyncio
async def test_run_explore_query_invalid_region_returns_empty():
    deals = await run_explore_query("ATH", "non_existent_region", "2026-09-15")
    assert deals == []

@pytest.mark.asyncio
async def test_run_explore_query_handles_provider_error_gracefully():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()
        
        def mock_search(origin, dst, date, currency="EUR"):
            if dst == "CDG":
                raise RuntimeError("Google Flights connection timeout")
            elif dst == "FCO":
                return [AsyncMock(price=40.0, airline="ITA Airways", typical_min=90.0, typical_max=110.0, country="Italy")]
            return []

        provider.search_flights.side_effect = mock_search
        provider_cls.return_value = provider

        deals = await run_explore_query("ATH", "europe", "2026-09-15")
        # CDG failed, but FCO succeeded! Explore query should return FCO without throwing an exception.
        assert len(deals) >= 1
        assert deals[0]["destination_code"] == "FCO"

@pytest.mark.asyncio
async def test_run_explore_query_ranking_diversity_cap_and_sort_by_price():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()
        
        # Mock 3 French airports:
        # - CDG: Price 50, Baseline 200 -> 75% discount (Highest!)
        # - ORY: Price 45, Baseline 150 -> 70% discount (2nd Highest!)
        # - NCE: Price 40, Baseline 80  -> 50% discount (3rd Highest in France -> Must be dropped by max-2 cap!)
        # - FCO (Italy): Price 40, Baseline 100 -> 60% discount
        # - SOF (Bulgaria): Price 20, Baseline 24 -> 16.67% discount
        def mock_search(origin, dst, date, currency="EUR"):
            if dst == "CDG":
                return [AsyncMock(price=50.0, airline="Air France", typical_min=190.0, typical_max=210.0, country="France")]
            elif dst == "ORY":
                return [AsyncMock(price=45.0, airline="Transavia", typical_min=140.0, typical_max=160.0, country="France")]
            elif dst == "NCE":
                return [AsyncMock(price=40.0, airline="EasyJet", typical_min=70.0, typical_max=90.0, country="France")]
            elif dst == "FCO":
                return [AsyncMock(price=40.0, airline="ITA Airways", typical_min=90.0, typical_max=110.0, country="Italy")]
            elif dst == "SOF":
                return [AsyncMock(price=20.0, airline="Ryanair", typical_min=22.0, typical_max=26.0, country="Bulgaria")]
            return []

        provider.search_flights.side_effect = mock_search
        provider_cls.return_value = provider

        # 1. Test sort_by="discount" with Diversity Cap (Max 2 French airports allowed: CDG [75%] and ORY [70%]; NCE [50%] dropped)
        deals_discount = await run_explore_query("ATH", "europe", "2026-09-15", max_budget=100.0, sort_by="discount")
        french_deals = [d for d in deals_discount if d.get("country") == "France"]
        assert len(french_deals) == 2  # Max 2 French destinations kept!
        french_codes = [d["destination_code"] for d in french_deals]
        assert "CDG" in french_codes and "ORY" in french_codes
        assert "NCE" not in french_codes  # NCE dropped by diversity cap!

        # Ranking Order: CDG (75%), ORY (70%), FCO (60%), SOF (16.67%)
        assert deals_discount[0]["destination_code"] == "CDG"
        assert deals_discount[1]["destination_code"] == "ORY"
        assert deals_discount[2]["destination_code"] == "FCO"
        assert deals_discount[3]["destination_code"] == "SOF"

        # 2. Test sort_by="price" (Lowest absolute price first: SOF [20], FCO [40], ORY [45], CDG [50])
        deals_price = await run_explore_query("ATH", "europe", "2026-09-15", max_budget=100.0, sort_by="price")
        assert deals_price[0]["destination_code"] == "SOF"  # 20 EUR lowest price first!
