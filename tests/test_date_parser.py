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
    dates = generate_date_sequence("2026-09-01", "2026-09-30", max_days=5)
    assert len(dates) == 5
    assert dates[0] == "2026-09-01"
    assert dates[-1] == "2026-09-05"

def test_generate_date_sequence_90_days():
    dates = generate_date_sequence("2026-08-17", "2026-11-14")
    assert len(dates) == 90

def test_generate_date_sequence_custom_98_days():
    from services.explore_engine import build_timeframe_date_range
    dep_range = build_timeframe_date_range(98)
    start_date, end_date = dep_range.split("..")
    dates = generate_date_sequence(start_date, end_date)
    assert len(dates) == 98



def test_get_preset_range_next_7_days():
    today = datetime.now(timezone.utc).date()
    start_str, end_str = get_preset_range("next_7_days")
    exp_start = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    exp_end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert start_str == exp_start
    assert end_str == exp_end
