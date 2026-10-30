from bot.formatting import (
    countdown, deal_report, digest_card, discount_badge, offer_line, progress_bar, progress_text, query_scope,
    short_date, short_window, split_message, tracker_card,
)
from database.models import Digest, Tracker
from providers.base import FlightOffer
from services.explore_engine import Deal, DealSection


def test_offer_line_html():
    offer = FlightOffer("ATH", "LON", "2027-04-03", price=120.0, airline="Aegean <Air>", is_direct=False,
                        departure_time="23:00", arrival_time="04:15", day_offset=1, typical_min=140.0,
                        typical_max=160.0, booking_url="https://example.com/?a=1&b=2")
    line = offer_line(offer, 0, show_date=True)
    assert line.startswith("1️⃣ ")
    assert '<a href="https://example.com/?a=1&amp;b=2"><b>€120.00</b></a>' in line
    assert "<b>20% OFF</b>" in line
    assert "(2027-04-03)" in line
    assert "Aegean &lt;Air&gt; (1+ Stops 🔄)" in line
    assert "23:00 ➔ 04:15 (+1)" in line


def test_discount_badge_variants():
    assert discount_badge(80, None) == ""
    assert "20% OFF" in discount_badge(80, 100)
    assert "25% above usual" in discount_badge(125, 100)
    assert discount_badge(80, 100, show_discount=False) == " (usually ~€100.00)"


def test_deal_report_numbers_across_sections():
    deal = Deal("ATH", "FCO", "Rome", "Italy", "2027-01-05", 40.0, "ITA", True, 100.0, 60.0)
    report = deal_report("<b>Title</b>", [DealSection("discount", [deal]), DealSection("price", [deal])])
    assert report.startswith("<b>Title</b>")
    assert "BIGGEST DISCOUNTS" in report and "CHEAPEST FLIGHTS" in report
    assert "1. <b>ATH ✈️ FCO</b>" in report and "2. <b>ATH ✈️ FCO</b>" in report
    assert report.count("60% OFF") == 1


def test_split_message_respects_limit_and_keeps_lines_whole():
    lines = [f"line {i} " + "x" * 50 for i in range(100)]
    chunks = split_message("\n".join(lines), limit=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    assert "\n".join(chunks).split("\n") == lines


def test_countdown_has_fixed_format():
    assert [countdown(s) for s in (0, 6.2, 59, 60, 754, 3600, 3725)] == [
        "0:00", "0:07", "0:59", "1:00", "12:34", "1:00:00", "1:02:05"]


def test_short_dates():
    from datetime import date
    this_year, next_year = date.today().year, date.today().year + 1
    assert short_date(f"{this_year}-10-31") == "31 Oct"
    assert short_date(f"{next_year}-01-28") == f"28 Jan {next_year}"
    assert short_window(f"{this_year}-10-31", f"{this_year}-11-29") == "31 Oct ➔ 29 Nov"


def test_progress_bar_keeps_its_width():
    assert progress_bar(0, 45) == "⬜" * 10
    assert progress_bar(27, 45) == "🟩" * 6 + "⬜" * 4
    assert progress_bar(45, 45) == "🟩" * 10
    assert progress_bar(0, 0) == "⬜" * 10


def test_progress_text_lines_are_short():
    text = progress_text("<b>Deals from ATH to Islands</b>", "31 Oct ➔ 29 Nov · 15 airports × 30 days", 365, 450, 37)
    lines = text.split("\n")
    assert lines[1] == "📅 31 Oct ➔ 29 Nov · 15 airports × 30 days"
    assert lines[3] == "🟩" * 8 + "⬜" * 2 + " 81%"
    assert lines[4].startswith("⏱️ <b>0:37</b> left · done around <b>")
    assert max(len(line) for line in lines[3:]) < 50


def test_query_scope():
    assert query_scope(15, 1) == "15 airports"
    assert query_scope(1, 5) == "5 days"
    assert query_scope(1, 1) == ""


def test_cards():
    tracker = Tracker(7, 1, "SKG", "MJT", "2027-09-03", None, 40.0, 6, True, "PAUSED", last_price_found=107.0)
    card = tracker_card(tracker)
    assert "⏸️ <b>Tracker #7</b>" in card and "€40.00" in card and "€107.00" in card

    digest = Digest(3, 1, "ATH", "latin_america", None, 30, None, None, "both", "Friday", "18:00", 5, "ACTIVE")
    card = digest_card(digest)
    assert "ATH ✈️ Latin America" in card and "every Friday at 18:00" in card
    assert "next 30 days" in card and "Any budget" in card
