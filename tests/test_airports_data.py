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

def test_new_airport_hubs_exist():
    from services.airports_data import get_region_airports
    
    asia_codes = [a["code"] for a in get_region_airports("asia")]
    assert "NRT" in asia_codes
    assert "TPE" in asia_codes
    
    na_codes = [a["code"] for a in get_region_airports("north_america")]
    assert "EWR" in na_codes
    assert "SEA" in na_codes

    latam_codes = [a["code"] for a in get_region_airports("latin_america")]
    assert "GIG" in latam_codes
    assert "MDE" in latam_codes

    africa_codes = [a["code"] for a in get_region_airports("africa")]
    assert "ZNZ" in africa_codes
    assert "SEZ" in africa_codes

    me_codes = [a["code"] for a in get_region_airports("middle_east")]
    assert "IST" in me_codes
    assert "BEY" in me_codes



def test_greek_islands_are_islands():
    codes = {a["code"] for a in get_region_airports("islands")}
    assert "SKG" not in codes and "KLX" not in codes
    assert {"JTR", "JMK", "HER", "RHO"} <= codes


def test_city_airport_lists_have_no_repeats():
    from services.airports_data import MULTI_AIRPORT_CITIES
    for city, codes in MULTI_AIRPORT_CITIES.items():
        assert len(codes) == len(set(codes)), city


def test_greek_airport_codes_are_right():
    from services.airports_data import airport_name
    assert "Kalamata" in airport_name("KLX") and airport_name("KTT") is None  # KTT is Kittilä, Finland
    assert "Lemnos" in airport_name("LXS") and airport_name("LXG") is None    # LXG is in Laos
