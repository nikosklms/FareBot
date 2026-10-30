from datetime import date

from bot.date_picker import RANGE, SINGLE, calendar_markup, shift_month


def buttons(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def test_shift_month_crosses_years():
    assert shift_month(2027, 1, -1) == (2026, 12)
    assert shift_month(2027, 12, 1) == (2028, 1)


def test_navigation_mode_and_cancel_buttons():
    data = [d for _, d in buttons(calendar_markup("x", 2027, 1, date(2026, 12, 1), mode=RANGE))]
    assert "x:nav:2026-12" in data and "x:nav:2027-02" in data
    assert "x:mode:single" in data and "cancel" in data
    single = [d for _, d in buttons(calendar_markup("x", 2027, 1, date(2026, 12, 1), mode=SINGLE))]
    assert "x:mode:range" in single


def test_past_days_disabled_and_leap_day_present():
    markup = calendar_markup("x", 2028, 2, date(2028, 2, 10))
    data = [d for _, d in buttons(markup)]
    assert "x:day:2028-02-29" in data
    assert "x:day:2028-02-10" in data
    assert "x:day:2028-02-09" not in data


def test_range_start_is_flagged_and_earlier_days_disabled():
    markup = calendar_markup("x", 2027, 9, date(2027, 1, 1), range_start=date(2027, 9, 15))
    labels = buttons(markup)
    assert ("🚩15", "x:day:2027-09-15") in labels
    assert ("14", "x:day:2027-09-14") not in labels
