"""The admin's /limits: everyone's limits, and limits of their own for one person."""
from bot.auth import limits_for
from bot.handlers.limits import YOURS
from bot.handlers.access import ADMIN_ONLY
from config import MAX_TRACKERS_PER_USER, MEMBER_MAX_ACTIVE, MEMBER_MAX_RANGE_DAYS
from database.models import APPROVED, EVERYONE, Limits
from tests.fakes import USER_ID, future
from utils.date_parser import MAX_RANGE_DAYS

MARIA = 555
NIKOS = 666


async def members(bot):
    db = bot.services.db
    for uid, handle, name in ((MARIA, "@maria", "Maria"), (NIKOS, "@nikos", "Nikos")):
        await db.request_access(uid, handle, name)
        await db.set_user_status(uid, APPROVED)


async def test_limits_lists_everyone_and_each_person(bot):
    await members(bot)
    await bot.send("/limits")
    text = bot.telegram.last_text
    assert f"<b>Everyone</b>: {MEMBER_MAX_ACTIVE} active · {MEMBER_MAX_RANGE_DAYS} days" in text
    assert f"<b>You</b>: {MAX_TRACKERS_PER_USER} active · {MAX_RANGE_DAYS} days" in text
    assert "Maria (@maria)" in text and "Nikos (@nikos)" in text
    buttons = bot.telegram.last_buttons()
    assert ("👥 Everyone", f"lim:who:{EVERYONE}") in buttons and ("👤 Maria", f"lim:who:{MARIA}") in buttons


async def test_changing_everyones_limits_applies_to_all_members(bot):
    await members(bot)
    await bot.send("/limits")
    await bot.press(f"lim:who:{EVERYONE}")
    await bot.press(f"lim:set:{EVERYONE}:a:5")
    await bot.press(f"lim:set:{EVERYONE}:d:90")
    assert "Active trackers + digests</b>: 5" in bot.telegram.last_text
    assert ("✅ 5", f"lim:set:{EVERYONE}:a:5") in bot.telegram.last_buttons()

    db = bot.services.db
    for uid in (MARIA, NIKOS):
        assert await limits_for(db, uid) == Limits(5, 90)
    assert await limits_for(db, USER_ID) == Limits(MAX_TRACKERS_PER_USER, MAX_RANGE_DAYS)

    await bot.send(f"/search ATH LON {future(1)}..{future(91)}", user_id=MARIA)
    assert "the most you can search is 90 days" in bot.telegram.last_text
    await bot.send("/help", user_id=NIKOS)
    assert "(up to 5 active)" in bot.telegram.last_text


async def test_one_person_can_get_limits_of_their_own(bot):
    await members(bot)
    db = bot.services.db
    await bot.press(f"lim:set:{EVERYONE}:a:2")
    await bot.press(f"lim:who:{MARIA}")
    assert "(everyone's)" in bot.telegram.last_text
    await bot.press(f"lim:set:{MARIA}:a:10")
    assert "Active trackers + digests</b>: 10 (their own)" in bot.telegram.last_text
    assert "Days ahead / date range</b>: 180 (everyone's)" in bot.telegram.last_text

    assert await limits_for(db, MARIA) == Limits(10, MEMBER_MAX_RANGE_DAYS)
    assert await limits_for(db, NIKOS) == Limits(2, MEMBER_MAX_RANGE_DAYS)
    for day in range(3):
        await bot.send(f"/track ATH LON {future(5 + day)} 100", user_id=MARIA)
    assert await db.count_active(MARIA) == 3
    for day in range(3):
        await bot.send(f"/track ATH LON {future(5 + day)} 100", user_id=NIKOS)
    assert "already have 2 active trackers and digests" in bot.telegram.last_text

    await bot.send("/limits")
    assert "Maria (@maria) · ID <code>555</code>: 10 active ✏️ · 180 days" in bot.telegram.last_text


async def test_own_limits_can_go_back_to_everyones(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:d:300")
    assert ("↩️ Use Everyone's (3 active · 180 days)", f"lim:reset:{MARIA}") in bot.telegram.last_buttons()
    await bot.press(f"lim:reset:{MARIA}")
    assert "Days ahead / date range</b>: 180 (everyone's)" in bot.telegram.last_text
    assert not any(data.startswith("lim:reset") for _, data in bot.telegram.last_buttons())
    assert await bot.services.db.get_limits() == {}


async def test_own_limits_are_forgotten_when_someone_is_removed(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:a:8")
    await bot.press(f"acc:rm:{MARIA}:l")
    assert await bot.services.db.get_limits(MARIA) == {}
    await bot.press(f"lim:set:{MARIA}:a:8")
    assert "doesn't have access anymore" in bot.telegram.calls_to("answerCallbackQuery")[-1]["text"]
    assert await bot.services.db.get_limits(MARIA) == {}


async def test_only_the_admin_can_change_limits(bot):
    await members(bot)
    await bot.send("/limits", user_id=MARIA)
    assert bot.telegram.last_text == ADMIN_ONLY
    await bot.press(f"lim:set:{EVERYONE}:a:20", user_id=MARIA)
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == ADMIN_ONLY
    assert await bot.services.db.get_limits() == {}


async def test_values_that_arent_offered_are_refused(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:a:999")
    assert "Pick one of the numbers shown" in bot.telegram.calls_to("answerCallbackQuery")[-1]["text"]
    await bot.press(f"lim:set:{USER_ID}:a:5")  # the admin's own limits aren't editable
    assert await bot.services.db.get_limits() == {}


async def test_picking_the_current_value_changes_nothing(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:a:5")
    edits = len(bot.telegram.calls_to("editMessageText"))
    await bot.press(f"lim:set:{MARIA}:a:5")
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == "It's already 5."
    assert len(bot.telegram.calls_to("editMessageText")) == edits


async def test_over_the_limit_the_message_says_how_many_to_remove(bot):
    await members(bot)
    db = bot.services.db
    for day in range(5):
        await db.create_tracker(MARIA, "ATH", "LON", future(5 + day), 100.0)
    await bot.press(f"lim:set:{MARIA}:a:2")
    await bot.send(f"/track ATH PAR {future(5)} 100", user_id=MARIA)
    assert ("You have 5 active trackers and digests, but the most you can have is now 2. "
            "Pause or delete 4 in /mytracks first.") in bot.telegram.last_text
    assert await db.count_active(MARIA) == 5  # nothing was paused


async def test_day_buttons_stop_at_the_users_limit(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:d:30")
    await bot.send("/explore", user_id=MARIA)
    await bot.send("ATH", user_id=MARIA)
    await bot.press("exp:org:ATH", user_id=MARIA)
    await bot.press("exp:reg:europe", user_id=MARIA)
    await bot.press("exp:sort:price", user_id=MARIA)
    days = [data for _, data in bot.telegram.last_buttons() if data.startswith("exp:when:days:")]
    assert days == ["exp:when:days:7", "exp:when:days:14", "exp:when:days:30"]

    await bot.send("/explore", user_id=NIKOS)
    await bot.send("ATH", user_id=NIKOS)
    await bot.press("exp:org:ATH", user_id=NIKOS)
    await bot.press("exp:reg:europe", user_id=NIKOS)
    await bot.press("exp:sort:price", user_id=NIKOS)
    assert "exp:when:days:90" in [data for _, data in bot.telegram.last_buttons()]


async def test_everyones_default_counts_as_already_set(bot):
    await bot.press(f"lim:who:{EVERYONE}")
    edits = len(bot.telegram.calls_to("editMessageText"))
    await bot.press(f"lim:set:{EVERYONE}:a:{MEMBER_MAX_ACTIVE}")
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == f"It's already {MEMBER_MAX_ACTIVE}."
    assert len(bot.telegram.calls_to("editMessageText")) == edits
    assert await bot.services.db.get_limits() == {}


async def test_the_admins_own_id_gets_a_clear_answer(bot):
    await bot.press(f"lim:set:{USER_ID}:a:5")
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == YOURS
    assert await bot.services.db.get_limits() == {}
