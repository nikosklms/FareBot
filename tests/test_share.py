import re

from bot.handlers.share import parse_payload, share_payload
from database.models import Digest, Tracker
from tests.fakes import USER_ID, future


def tracker(**changes):
    fields = dict(id=1, user_id=USER_ID, origin_code="ATH", destination_code="LON", departure_date=future(10),
                  departure_date_end=future(15), max_budget=85.5, frequency_hours=12, direct_only=True, status="ACTIVE")
    return Tracker(**{**fields, **changes})


def digest(**changes):
    fields = dict(id=2, user_id=USER_ID, origin_code="SKG", region="latin_america", max_budget=None, days_ahead=None,
                  departure_date=future(20), departure_date_end=future(40), sort_mode="discount",
                  delivery_day="Tuesday", delivery_time="07:05", max_results=20, status="ACTIVE")
    return Digest(**{**fields, **changes})


def test_payloads_round_trip_and_fit_telegrams_limits():
    kind, s = parse_payload(share_payload(tracker()))
    assert kind == "t"
    assert s == {"origin": "ATH", "destination": "LON", "start": future(10), "end": future(15),
                 "direct_only": True, "budget": 85.5, "hours": 12}

    kind, s = parse_payload(share_payload(digest()))
    assert kind == "g"
    assert (s["region"], s["days"], s["start"], s["end"], s["sort"], s["budget"], s["day"], s["time"], s["limit"]) == \
        ("latin_america", None, future(20), future(40), "discount", None, "Tuesday", "07:05", 20)

    _, s = parse_payload(share_payload(digest(days_ahead=30, departure_date=None, departure_date_end=None)))
    assert (s["days"], s["start"]) == (30, None)

    # The longest realistic link still fits the 64-character start parameter and, with "sh:add:", callback data.
    longest = share_payload(digest(max_budget=99999.99))
    assert len(longest) + len("sh:add:") <= 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", longest)


def test_broken_payloads_are_refused():
    good = share_payload(tracker())
    for bad in ["", "t", "x-ATH", good + "-1", good.replace("ATH", "A1H"), good.replace("-12", "-1"),
                share_payload(tracker(max_budget=0)), share_payload(digest()).replace("latin_america", "mars")]:
        assert parse_payload(bad) is None, bad


async def test_share_button_sends_a_link(bot):
    created = await bot.services.db.create_tracker(USER_ID, "ATH", "LON", future(10), 100.0)
    await bot.send("/mytracks")
    await bot.press(bot.telegram.button_data("Share"))
    assert f"https://t.me/farebot?start={share_payload(created)}" in bot.telegram.last_text


async def test_opening_a_tracker_link_adds_it(bot):
    payload = share_payload(tracker())
    await bot.send(f"/start {payload}")
    assert "Shared tracker" in bot.telegram.last_text and "ATH ✈️ LON" in bot.telegram.last_text

    await bot.press(bot.telegram.button_data("Add This Tracker"))
    [added] = await bot.services.db.list_trackers(USER_ID)
    assert (added.departure_date_end, added.direct_only, added.max_budget, added.frequency_hours) == \
        (future(15), True, 85.5, 12)
    assert bot.jobs(f"tracker_job_{added.id}")

    await bot.press(f"sh:add:{payload}")
    assert "already tracking" in bot.telegram.last_text
    assert len(await bot.services.db.list_trackers(USER_ID)) == 1


async def test_opening_a_digest_link_adds_it(bot):
    await bot.send(f"/start {share_payload(digest())}")
    await bot.press(bot.telegram.button_data("Add This Digest"))
    [added] = await bot.services.db.list_digests(USER_ID)
    assert (added.region, added.delivery_day, added.delivery_time, added.max_results) == \
        ("latin_america", "Tuesday", "07:05", 20)


async def test_expired_broken_and_declined_links(bot):
    await bot.send(f"/start {share_payload(tracker(departure_date='2020-01-01', departure_date_end=None))}")
    assert "dates have passed" in bot.telegram.last_text and not bot.telegram.last_buttons()

    await bot.send("/start t-ATH")
    assert "broken" in bot.telegram.last_text

    await bot.send(f"/start {share_payload(tracker())}")
    await bot.press("sh:no")
    assert "Not added" in bot.telegram.last_text
    assert await bot.services.db.list_trackers(USER_ID) == []

    await bot.send("/start")
    assert "Welcome" in bot.telegram.last_text
