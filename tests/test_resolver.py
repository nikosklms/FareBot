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


@pytest.mark.parametrize("typed, expected_first", [
    ("la", "LAX"), ("lossangeles", "LAX"), ("athnes", "ATH"), ("sidney", "SYD"),
    ("crete", "HER"), ("korea", "SEL"), ("kos", "KGS"), ("Zürich", "ZRH"),
    ("seattle", "SEA"), ("zanzibar", "ZNZ"), ("hong kong", "HKG"),
])
def test_resolver_guesses_what_people_type(typed, expected_first):
    assert LocationResolver().resolve(typed)[0][0] == expected_first


def test_city_codes_come_before_single_airports():
    codes = [m[0] for m in LocationResolver().resolve("paris")]
    assert codes[:3] == ["PAR", "CDG", "ORY"]


def test_short_text_matches_word_starts_not_middles():
    codes = [m[0] for m in LocationResolver().resolve("la")]
    assert "KLX" not in codes and "JMK" not in codes  # 'Kalamata', 'Island'


def test_always_guesses_and_offers_unlisted_codes():
    resolver = LocationResolver()
    assert len(resolver.resolve("lol")) == 5
    assert resolver.resolve("bhx")[0][0] == "BHX"
    assert [m[0] for m in resolver.resolve("kos")][:2] == ["KGS", "KOS"]
    assert resolver.resolve("   ") == []


@pytest.mark.parametrize("typed, code", [("HAM", "HAM"), ("san", "SAN"), ("BRI", "BRI"), ("ath", "ATH")])
def test_shortcuts_take_three_letters_as_a_code(typed, code):
    assert LocationResolver().best_guess(typed) == code


def test_shortcut_names_use_the_best_match():
    resolver = LocationResolver()
    assert resolver.best_guess("thessaloniki") == "SKG"
    assert resolver.best_guess("Los Angeles") == "LAX"


@pytest.mark.parametrize("typed, code", [
    ("kos", "KGS"),        # the island, not the code KOS (Sihanoukville)
    ("san", "SAN"),        # first word of several names, so still a code
    ("bod", "BOD"),        # not a whole word of any name, so a code
    ("kalamata", "KLX"),
    ("lemnos", "LXS"),
    ("londn", "LON"),      # typos still work
    ("salonika", "SKG"),
])
def test_shortcut_guesses(typed, code):
    assert LocationResolver().best_guess(typed) == code


@pytest.mark.parametrize("typed", ["bari", "<b>", "x", "qqqq", "geneva"])
def test_shortcuts_dont_guess_weak_matches(typed):
    assert LocationResolver().best_guess(typed) is None
