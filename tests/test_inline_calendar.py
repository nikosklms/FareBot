from bot.inline_calendar import create_calendar, parse_calendar_callback

def test_calendar_rendering_and_actions():
    # Test markup structure for single and range modes
    markup_single = create_calendar(2026, 9, mode="single")
    markup_range = create_calendar(2026, 9, mode="range")
    
    button_datas_single = [b.callback_data for row in markup_single.inline_keyboard for b in row]
    button_datas_range = [b.callback_data for row in markup_range.inline_keyboard for b in row]

    # Verify nav actions, mode toggle, cancel button
    assert any("cal_nav_" in d for d in button_datas_single)
    assert any("cal_mode_range" in d for d in button_datas_single)
    assert any("cal_mode_single" in d for d in button_datas_range)
    assert any("cal_cancel" in d for d in button_datas_single)

    # Test callback parser for day, nav, mode, and cancel
    action_day, data_day = parse_calendar_callback("cal_day_2026-09-15")
    assert action_day == "DAY"
    assert data_day == "2026-09-15"

    action_nav, data_nav = parse_calendar_callback("cal_nav_2026-10")
    assert action_nav == "NAV"
    assert data_nav == "2026-10"

    action_mode, data_mode = parse_calendar_callback("cal_mode_range")
    assert action_mode == "MODE"
    assert data_mode == "range"

def test_calendar_year_boundary_navigation():
    # January year boundary -> prev month should be December of previous year
    markup_jan = create_calendar(2026, 1)
    nav_jan = [b.callback_data for row in markup_jan.inline_keyboard for b in row if "cal_nav_" in b.callback_data]
    assert "cal_nav_2025-12" in nav_jan
    assert "cal_nav_2026-02" in nav_jan

    # December year boundary -> next month should be January of next year
    markup_dec = create_calendar(2026, 12)
    nav_dec = [b.callback_data for row in markup_dec.inline_keyboard for b in row if "cal_nav_" in b.callback_data]
    assert "cal_nav_2026-11" in nav_dec
    assert "cal_nav_2027-01" in nav_dec

def test_calendar_leap_year_february():
    # 2028 is a leap year (29 days in Feb)
    markup_leap = create_calendar(2028, 2)
    day_buttons = [b.callback_data for row in markup_leap.inline_keyboard for b in row if "cal_day_" in b.callback_data]
    assert "cal_day_2028-02-29" in day_buttons
