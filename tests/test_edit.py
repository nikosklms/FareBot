from database.models import ACTIVE, EXPIRED, PAUSED
from tests.fakes import USER_ID, future

OTHER_USER = 456


async def make_tracker(bot, **kwargs):
    return await bot.services.db.create_tracker(USER_ID, kwargs.pop("origin", "ATH"), "LON",
                                                kwargs.pop("start", future(10)), 100.0, **kwargs)


async def make_digest(bot, **kwargs):
    return await bot.services.db.create_digest(USER_ID, "ATH", "europe", **{"days_ahead": 30, **kwargs})


async def test_mytracks_cards_offer_edit(bot):
    tracker = await make_tracker(bot)
    await bot.send("/mytracks")
    assert bot.telegram.button_data("Edit") == f"dash:edit:t:{tracker.id}"


async def test_menu_lists_fields_for_each_kind(bot):
    tracker = await make_tracker(bot)
    digest = await make_digest(bot)
    await bot.press(f"dash:edit:t:{tracker.id}")
    assert f"Tracker #{tracker.id}" in bot.telegram.last_text
    assert [label for label, _ in bot.telegram.last_buttons()] == [
        "📅 Dates", "⚙️ Flights", "🎯 Budget", "🔄 Checks", "✅ Done"]

    await bot.press(f"dash:edit:d:{digest.id}")
    assert [label for label, _ in bot.telegram.last_buttons()] == [
        "🎯 Budget", "📅 Departures", "📊 Ranking", "🔢 Deals Shown", "⏰ Day", "🕒 Time", "✅ Done"]


async def test_edit_every_tracker_field(bot):
    tracker = await make_tracker(bot)
    await bot.press(f"dash:edit:t:{tracker.id}")

    await bot.press("edit:field:dates")
    await bot.send(f"{future(20)}..{future(25)}")
    assert "Saved" in bot.telegram.last_text
    await bot.press("edit:field:flights")
    await bot.press("edit:direct:1")
    await bot.press("edit:field:budget")
    await bot.send("abc")
    assert "not a valid budget" in bot.telegram.last_text
    await bot.send("€65")
    await bot.press("edit:field:frequency")
    await bot.press("edit:freq:24")

    updated = await bot.services.db.get_tracker(tracker.id)
    assert (updated.departure_date, updated.departure_date_end) == (future(20), future(25))
    assert (updated.direct_only, updated.max_budget, updated.frequency_hours) == (True, 65.0, 24)
    assert bot.jobs("tracker_job_") == [f"tracker_job_{tracker.id}"]

    await bot.press("edit:done")
    assert bot.telegram.button_data("Edit") == f"dash:edit:t:{tracker.id}"
    assert "€65.00" in bot.telegram.last_text and "every 24 hours" in bot.telegram.last_text


async def test_edit_every_digest_field_and_reschedule(bot):
    digest = await make_digest(bot)
    await bot.press(f"dash:edit:d:{digest.id}")

    await bot.press("edit:field:budget")
    await bot.press("edit:bud:80")
    await bot.press("edit:field:window")
    await bot.press("edit:when:days:60")
    await bot.press("edit:field:sort")
    await bot.press("edit:sort:price")
    await bot.press("edit:field:limit")
    await bot.send("7")
    await bot.press("edit:field:day")
    await bot.press("edit:day:Tuesday")
    await bot.press("edit:field:time")
    await bot.send("8:05")

    updated = await bot.services.db.get_digest(digest.id)
    assert (updated.max_budget, updated.days_ahead, updated.sort_mode, updated.max_results) == (80.0, 60, "price", 7)
    assert (updated.delivery_day, updated.delivery_time) == ("Tuesday", "08:05")
    [job] = bot.app.job_queue.get_jobs_by_name(f"digest_job_{digest.id}")
    assert "day_of_week='tue'" in str(job.job.trigger) and "hour='8'" in str(job.job.trigger)


async def test_digest_window_can_switch_to_fixed_dates_and_any_budget(bot):
    digest = await make_digest(bot, max_budget=50.0)
    await bot.press(f"dash:edit:d:{digest.id}")
    await bot.press("edit:field:window")
    await bot.press("edit:when:cal:open")
    await bot.press(f"edit:when:cal:day:{future(30)}")
    await bot.press(f"edit:when:cal:day:{future(40)}")
    await bot.press("edit:field:budget")
    await bot.send("0")

    updated = await bot.services.db.get_digest(digest.id)
    assert (updated.days_ahead, updated.departure_date, updated.departure_date_end) == (None, future(30), future(40))
    assert updated.max_budget is None


async def test_alert_budget_button_rearms_paused_tracker_without_touching_the_alert(bot):
    tracker = await make_tracker(bot)
    await bot.services.db.set_tracker_status(tracker.id, PAUSED)

    await bot.press(f"dash:budget:t:{tracker.id}")
    assert bot.telegram.calls[-1][0] == "sendMessage"  # a new message, so the alert stays as it was
    assert "budget is now €100.00" in bot.telegram.last_text
    await bot.send("45")

    updated = await bot.services.db.get_tracker(tracker.id)
    assert (updated.max_budget, updated.status) == (45.0, ACTIVE)
    assert "resumed" in bot.telegram.last_text
    assert bot.jobs("tracker_job_") == [f"tracker_job_{tracker.id}"]


async def test_new_dates_revive_an_expired_tracker(bot):
    tracker = await make_tracker(bot, start="2020-01-01")
    await bot.services.db.set_tracker_status(tracker.id, EXPIRED)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:dates")
    await bot.press("edit:date:preset:next_7_days")

    assert (await bot.services.db.get_tracker(tracker.id)).status == ACTIVE
    assert "active again" in bot.telegram.last_text


async def test_back_returns_to_the_menu_without_saving(bot):
    tracker = await make_tracker(bot)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:frequency")
    await bot.press("back")
    assert "What do you want to change?" in bot.telegram.last_text

    await bot.press("edit:field:dates")
    await bot.press("edit:date:cal:open")
    await bot.press("edit:date:cal:close")
    assert "New dates?" in bot.telegram.last_text
    assert (await bot.services.db.get_tracker(tracker.id)).frequency_hours == 6


async def test_cannot_edit_other_users_items(bot):
    tracker = await bot.services.db.create_tracker(OTHER_USER, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:t:{tracker.id}")
    assert bot.telegram.alerts[-1] == "This item no longer exists."


async def test_cancel_ends_the_editor(bot):
    tracker = await make_tracker(bot)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:budget")
    await bot.send("/cancel")
    await bot.send("45")
    assert (await bot.services.db.get_tracker(tracker.id)).max_budget == 100.0


async def test_only_the_newest_wizard_answers_typed_text(bot):
    tracker = await make_tracker(bot)
    await bot.send("/search")
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:budget")
    replies = len(bot.telegram.texts)
    await bot.send("45")

    assert (await bot.services.db.get_tracker(tracker.id)).max_budget == 45.0
    assert len(bot.telegram.texts) == replies + 1  # only the editor replied; /search stayed quiet


async def test_warns_when_new_budget_is_above_last_price(bot):
    tracker = await make_tracker(bot)
    await bot.services.db.record_price(tracker.id, 499.0, "Asiana")
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:budget")
    await bot.send("949")
    assert "last price found was €499.00, already below this budget" in bot.telegram.last_text
    await bot.press("edit:field:budget")
    await bot.send("450")
    assert "already below" not in bot.telegram.last_text


async def test_buttons_on_an_older_editor_message_are_refused(bot):
    from bot.handlers.edit import OUT_OF_DATE
    db = bot.services.db
    digest = await db.create_digest(USER_ID, "ATH", "europe", days_ahead=30)
    tracker = await db.create_tracker(USER_ID, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:d:{digest.id}", message_id=501)
    await bot.press("edit:field:budget", message_id=501)
    await bot.press(f"dash:budget:t:{tracker.id}", message_id=777)  # the price alert's Set Lower Budget

    await bot.press("edit:bud:50", message_id=501)  # the digest's old budget buttons
    assert bot.telegram.alerts[-1] == OUT_OF_DATE
    await bot.press("edit:bud:0", message_id=501)
    assert (await db.get_tracker(tracker.id)).max_budget == 100.0
    assert (await db.get_digest(digest.id)).max_budget is None


async def test_editing_a_deleted_item_says_so(bot):
    db = bot.services.db
    tracker = await db.create_tracker(USER_ID, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await db.delete_tracker(tracker.id)
    await bot.press("edit:field:budget")
    assert "no longer exists" in bot.telegram.last_text


async def test_a_digest_field_on_a_tracker_does_nothing(bot):
    tracker = await bot.services.db.create_tracker(USER_ID, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:sort")
    assert "Something went wrong" not in bot.telegram.last_text
    await bot.press("edit:field:budget")  # the editor still works
    assert "budget is now" in bot.telegram.last_text


async def test_editing_dates_cant_create_a_duplicate(bot):
    db = bot.services.db
    first = await db.create_tracker(USER_ID, "ATH", "LON", future(5), 100.0)
    second = await db.create_tracker(USER_ID, "ATH", "LON", future(9), 100.0)
    await bot.press(f"dash:edit:t:{second.id}")
    await bot.press("edit:field:dates")
    await bot.send(future(5))
    assert f"Tracker #{first.id} already watches exactly that" in bot.telegram.last_text
    assert (await db.get_tracker(second.id)).departure_date == future(9)
