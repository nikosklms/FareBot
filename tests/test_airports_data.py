from services.airports_data import GLOBAL_REGIONS_AIRPORTS, get_region_airports

def test_global_regions_airports_structure():
    expected_regions = [
        "europe", "islands", "middle_east", "asia",
        "africa", "oceania", "latin_america", "north_america"
    ]
    for region in expected_regions:
        assert region in GLOBAL_REGIONS_AIRPORTS
        airports = get_region_airports(region)
        assert len(airports) >= 5

    # Verify primary European hubs
    europe_codes = [a["code"] for a in get_region_airports("europe")]
    assert "CDG" in europe_codes
    assert "FCO" in europe_codes
    assert "MAD" in europe_codes
    assert "VIE" in europe_codes
    assert "OTP" in europe_codes
