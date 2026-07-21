import pytest
from services.resolver import LocationResolver

def test_resolver_exact_match():
    resolver = LocationResolver()
    matches = resolver.resolve("ATH")
    assert len(matches) > 0
    assert matches[0][0] == "ATH"
    assert "Athens" in matches[0][1]

def test_resolver_typo_match():
    resolver = LocationResolver()
    matches = resolver.resolve("athen")
    assert len(matches) > 0
    assert matches[0][0] == "ATH"

def test_resolver_city_search():
    resolver = LocationResolver()
    matches = resolver.resolve("london")
    assert len(matches) > 0
    iata_codes = [m[0] for m in matches]
    assert any(code in ["LON", "LHR", "LGW", "STN"] for code in iata_codes)

def test_resolver_thessaloniki():
    resolver = LocationResolver()
    matches = resolver.resolve("thessaloniki")
    assert len(matches) > 0
    assert matches[0][0] == "SKG"

def test_resolver_greek_islands():
    resolver = LocationResolver()
    for island, expected_iata in [("santorini", "JTR"), ("mykonos", "JMK"), ("heraklion", "HER"), ("rhodes", "RHO")]:
        matches = resolver.resolve(island)
        assert len(matches) > 0
        assert matches[0][0] == expected_iata

def test_resolver_global_cities():
    resolver = LocationResolver()
    for city, expected_iatas in [("tokyo", ["TYO", "HND", "NRT"]), ("dubai", ["DXB", "DWC"]), ("sydney", ["SYD"]), ("cairo", ["CAI"])]:
        matches = resolver.resolve(city)
        assert len(matches) > 0
        matched_iatas = [m[0] for m in matches]
        assert any(code in expected_iatas for code in matched_iatas)
