from config import MAX_TRACKERS_PER_USER
from database.models import PAUSED
from tests.fakes import USER_ID, future


async def test_full_wizard_creates_and_schedules_tracker(bot):
    await bot.send("/track")
    assert "Step 1/6" in bot.telegram.last_text
    await bot.send("SKG")
    await bot.press("trk:org:SKG")
    await bot.send("Mytilene")
    await bot.press(bot.telegram.button_data("MJT"))
    await bot.press("trk:date:preset:next_14_days")
    await bot.press("trk:direct:1")
    assert "Step 5/6" in bot.telegram.last_text
    await bot.send("abc")
    assert "price above 0" in bot.telegram.last_text
    await bot.send("€45")
    assert "Step 6/6" in bot.telegram.last_text
    await bot.press("trk:freq:12")

    [tracker] = await bot.services.db.list_trackers(USER_ID)
    assert (tracker.origin_code, tracker.destination_code) == ("SKG", "MJT")
    assert (tracker.departure_date, tracker.departure_date_end) == (future(1), future(14))
    assert tracker.max_budget == 45.0 and tracker.frequency_hours == 12 and tracker.direct_only
    assert "Tracking started" in bot.telegram.last_text
    assert bot.jobs("tracker_job_") == [f"tracker_job_{tracker.id}"]


async def test_shortcut(bot):
    await bot.send(f"/track ATH LON {future(5)}..{future(9)} 150 direct")
    [tracker] = await bot.services.db.list_trackers(USER_ID)
    assert (tracker.departure_date, tracker.departure_date_end, tracker.max_budget) == (future(5), future(9), 150.0)
    assert tracker.direct_only and tracker.frequency_hours == 6

    await bot.send("/track ATH LON")
    assert "Usage" in bot.telegram.last_text
    await bot.send(f"/track ATH LON {future(5)} cheap")
    assert "couldn't read the date or budget" in bot.telegram.last_text
    await bot.send(f"/track ATH LON {future(5)} -5")
    assert "budget must be above 0" in bot.telegram.last_text
    await bot.send(f"/track ATH LON {future(5)}..{future(400)} 100")
    assert "range is too long" in bot.telegram.last_text


async def test_duplicate_is_refused_with_edit_budget_button(bot):
    await bot.send(f"/track ATH LON {future(5)} 150")
    [tracker] = await bot.services.db.list_trackers(USER_ID)
    await bot.send(f"/track ATH LON {future(5)} 90")

    assert "already tracking" in bot.telegram.last_text
    assert bot.telegram.button_data("Edit Its Budget") == f"dash:budget:t:{tracker.id}"
    assert len(await bot.services.db.list_trackers(USER_ID)) == 1


async def test_limit_counts_trackers_and_digests(bot):
    db = bot.services.db
    for i in range(MAX_TRACKERS_PER_USER - 1):
        await db.create_tracker(USER_ID, "ATH", "LON", future(10 + i), 100.0)
    await db.create_digest(USER_ID, "ATH", "europe", days_ahead=30)

    await bot.send(f"/track ATH PAR {future(5)} 150")
    assert f"already have {MAX_TRACKERS_PER_USER} active" in bot.telegram.last_text


async def test_track_button_from_results(bot):
    await bot.press(f"trk:add:ATH:LON:{future(5)}:{future(8)}:72.50:1")

    [tracker] = await bot.services.db.list_trackers(USER_ID)
    assert (tracker.departure_date_end, tracker.max_budget, tracker.direct_only) == (future(8), 72.5, True)
    assert bot.telegram.alerts[-1] == "✅ Tracking started"
    assert "Tracking started" in bot.telegram.last_text

    await bot.press(f"trk:add:ATH:LON:{future(5)}:{future(8)}:60.00:1")
    assert "already tracking" in bot.telegram.last_text
    await bot.press(f"trk:add:ATH:LON:{future(5)}::60.00:0")
    assert "Tracking started" in bot.telegram.last_text  # a single day is a different tracker


async def test_paused_duplicate_still_counts(bot):
    await bot.send(f"/track ATH LON {future(5)} 150")
    [tracker] = await bot.services.db.list_trackers(USER_ID)
    await bot.services.db.set_tracker_status(tracker.id, PAUSED)
    await bot.press(f"trk:add:ATH:LON:{future(5)}::60.00:0")
    assert "already tracking" in bot.telegram.last_text
