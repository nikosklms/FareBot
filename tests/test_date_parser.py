import pytest
from datetime import date, timedelta
from utils.date_parser import (
    days_ahead_window, describe_window, generate_date_sequence, get_preset_range, is_past, parse_date_or_range,
    today_local,
)

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

def test_days_ahead_window_covers_requested_days():
    start_date, end_date = days_ahead_window(98, today=date(2027, 1, 1))
    assert (start_date, end_date) == ("2027-01-02", "2027-04-09")
    assert len(generate_date_sequence(start_date, end_date)) == 98


def test_parse_reversed_and_same_day_ranges():
    assert parse_date_or_range("2026-09-15..2026-09-01") == ("2026-09-01", "2026-09-15")
    assert parse_date_or_range("2026-09-01..2026-09-01") == ("2026-09-01", None)


@pytest.mark.parametrize("bad", ["", "tomorrow", "2026-13-01", "2026-09-01..soon"])
def test_parse_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_date_or_range(bad)


def test_this_weekend_is_next_saturday_and_sunday():
    assert get_preset_range("this_weekend", today=date(2027, 1, 6)) == ("2027-01-09", "2027-01-10")
    assert get_preset_range("this_weekend", today=date(2027, 1, 9)) == ("2027-01-16", "2027-01-17")


def test_is_past_and_describe_window():
    assert is_past("2027-01-01", today=date(2027, 1, 2))
    assert not is_past("2027-01-02", today=date(2027, 1, 2))
    assert describe_window("2027-01-01", None) == "2027-01-01"
    assert describe_window("2027-01-01", "2027-01-05") == "2027-01-01 ➔ 2027-01-05"


def test_get_preset_range_next_7_days():
    today = today_local()
    start_str, end_str = get_preset_range("next_7_days")
    exp_start = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    exp_end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert start_str == exp_start
    assert end_str == exp_end


def test_window_problem():
    from utils.date_parser import window_problem
    today = date(2027, 1, 10)
    assert window_problem("2027-01-09", None, today) == "That date is in the past. Pick a future date."
    assert window_problem("2027-01-10", "2027-12-05", today) is None  # 330 days
    assert "too long" in window_problem("2027-01-10", "2027-12-06", today)


def test_today_follows_the_bot_timezone(monkeypatch):
    import utils.date_parser as dp
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(dp, "_bot_timezone", lambda: ZoneInfo("Pacific/Kiritimati"))  # UTC+14
    ahead = dp.today_local()
    monkeypatch.setattr(dp, "_bot_timezone", lambda: ZoneInfo("Pacific/Pago_Pago"))  # UTC-11
    assert (ahead - dp.today_local()).days == 1
