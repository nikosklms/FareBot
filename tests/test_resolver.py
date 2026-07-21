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
