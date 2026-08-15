import pytest
from datetime import datetime, timedelta, timezone
from utils.date_parser import parse_date_or_range, generate_date_sequence, get_preset_range

def test_parse_single_iso_date():
    start, end = parse_date_or_range("2026-09-01")
    assert start == "2026-09-01"
    assert end is None

def test_parse_range_dots():
    start, end = parse_date_or_range("2026-09-01..2026-09-15")
    assert start == "2026-09-01"
    assert end == "2026-09-15"

def test_parse_range_colon():
    start, end = parse_date_or_range("2026-09-01:2026-09-10")
    assert start == "2026-09-01"
    assert end == "2026-09-10"

def test_parse_range_word_to():
    start, end = parse_date_or_range("2026-09-01 to 2026-09-05")
    assert start == "2026-09-01"
    assert end == "2026-09-05"

def test_generate_date_sequence_normal():
    dates = generate_date_sequence("2026-09-01", "2026-09-03", max_days=14)
    assert dates == ["2026-09-01", "2026-09-02", "2026-09-03"]

def test_generate_date_sequence_capped():
    dates_consec = generate_date_sequence("2026-09-01", "2026-09-30", max_days=5, sample_evenly=False)
    assert len(dates_consec) == 5
    assert dates_consec[0] == "2026-09-01"
    assert dates_consec[-1] == "2026-09-05"

    dates_sampled = generate_date_sequence("2026-09-01", "2026-09-30", max_days=5, sample_evenly=True)
    assert len(dates_sampled) == 5
    assert dates_sampled[0] == "2026-09-01"
    assert dates_sampled[-1] == "2026-09-25"

def test_get_preset_range_next_7_days():
    today = datetime.now(timezone.utc).date()
    start_str, end_str = get_preset_range("next_7_days")
    exp_start = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    exp_end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert start_str == exp_start
    assert end_str == exp_end
