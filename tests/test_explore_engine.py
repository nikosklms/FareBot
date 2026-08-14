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
async def test_run_explore_query_excludes_origin_country():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()
        
        def mock_search(origin, dst, date, currency="EUR"):
            if dst == "SKG":  # Greece (Same country as ATH)
                return [AsyncMock(price=30.0, airline="Aegean", typical_min=80.0, typical_max=100.0, country="Greece")]
            elif dst == "FCO":  # Italy
                return [AsyncMock(price=40.0, airline="ITA Airways", typical_min=90.0, typical_max=110.0, country="Italy")]
            return []

        provider.search_flights.side_effect = mock_search
        provider_cls.return_value = provider

        deals = await run_explore_query("ATH", "europe", "2026-09-15")
        returned_codes = [d["destination_code"] for d in deals]
        assert "SKG" not in returned_codes  # SKG (Greece) excluded because origin ATH is in Greece!
        assert "FCO" in returned_codes      # FCO (Italy) included!

@pytest.mark.asyncio
async def test_run_explore_query_excludes_cyprus_for_greece_origin():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()
        
        def mock_search(origin, dst, date, currency="EUR"):
            if dst == "LCA":  # Cyprus
                return [AsyncMock(price=35.0, airline="Wizz Air", typical_min=80.0, typical_max=100.0, country="Cyprus")]
            elif dst == "FCO":  # Italy
                return [AsyncMock(price=40.0, airline="ITA Airways", typical_min=90.0, typical_max=110.0, country="Italy")]
            return []

        provider.search_flights.side_effect = mock_search
        provider_cls.return_value = provider

        deals = await run_explore_query("ATH", "europe", "2026-09-15")
        returned_codes = [d["destination_code"] for d in deals]
        assert "LCA" not in returned_codes  # LCA (Cyprus) excluded when origin is Greece!
        assert "FCO" in returned_codes      # FCO (Italy) included!

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

        deals_discount = await run_explore_query("ATH", "europe", "2026-09-15", max_budget=100.0, sort_by="discount")
        french_deals = [d for d in deals_discount if d.get("country") == "France"]
        assert len(french_deals) == 2  # Max 2 French destinations kept!
        french_codes = [d["destination_code"] for d in french_deals]
        assert "CDG" in french_codes and "ORY" in french_codes
        assert "NCE" not in french_codes  # NCE dropped by diversity cap!

        assert deals_discount[0]["destination_code"] == "CDG"
        assert deals_discount[1]["destination_code"] == "ORY"
        assert deals_discount[2]["destination_code"] == "FCO"
        assert deals_discount[3]["destination_code"] == "SOF"

        deals_price = await run_explore_query("ATH", "europe", "2026-09-15", max_budget=100.0, sort_by="price")
        assert deals_price[0]["destination_code"] == "SOF"  # 20 EUR lowest price first!
