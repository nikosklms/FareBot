"""The admin's /limits: everyone's limits, and limits of their own for one person."""
from bot.auth import limits_for
from bot.handlers.limits import YOURS
from bot.handlers.access import ADMIN_ONLY
from config import MAX_TRACKERS_PER_USER, MEMBER_MAX_ACTIVE, MEMBER_MAX_RANGE_DAYS
from database.models import ACTIVE, APPROVED, EVERYONE, EXPIRED, PAUSED, Limits
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


async def test_button_values_must_be_in_range(bot):
    await members(bot)
    await bot.press(f"lim:set:{MARIA}:a:999")
    assert "Pick a number from 1 to 20." == bot.telegram.calls_to("answerCallbackQuery")[-1]["text"]
    await bot.press(f"lim:set:{USER_ID}:a:5")  # the admin's own limits aren't editable
    assert await bot.services.db.get_limits() == {}

    await bot.press(f"lim:set:{MARIA}:a:4")  # not a button, but in range, as typing allows
    assert await limits_for(bot.services.db, MARIA) == Limits(4, MEMBER_MAX_RANGE_DAYS)


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


def sent_to(bot, chat_id):
    return [call for call in bot.telegram.calls_to("sendMessage") if call["chat_id"] == chat_id]


async def test_the_admin_can_type_a_number(bot):
    await members(bot)
    await bot.press(f"lim:who:{MARIA}")
    await bot.press(f"lim:type:{MARIA}:a")
    assert "Type how many trackers and digests Maria can have active, from 1 to 20" in bot.telegram.last_text
    for wrong in ("0", "21", "seven", "4.5"):
        await bot.send(wrong)
        assert "Type a whole number from 1 to 20" in bot.telegram.last_text
    await bot.send("7")
    assert "✅ <b>Saved.</b>" in bot.telegram.last_text and "Active trackers + digests</b>: 7 (their own)" in bot.telegram.last_text
    assert await limits_for(bot.services.db, MARIA) == Limits(7, MEMBER_MAX_RANGE_DAYS)

    await bot.send("9")  # the typing step has ended, so this does nothing
    assert await limits_for(bot.services.db, MARIA) == Limits(7, MEMBER_MAX_RANGE_DAYS)


async def test_typed_days_for_everyone_start_at_30(bot):
    await members(bot)
    await bot.press(f"lim:type:{EVERYONE}:d")
    assert "how many days ahead everyone can search, from 30 to 330" in bot.telegram.last_text
    await bot.send("29")
    assert "from 30 to 330" in bot.telegram.last_text
    await bot.send("45")
    assert await limits_for(bot.services.db, NIKOS) == Limits(MEMBER_MAX_ACTIVE, 45)


async def test_back_from_typing_shows_the_person_again(bot):
    await members(bot)
    await bot.press(f"lim:type:{MARIA}:d")
    await bot.press("back")
    assert "👤 Maria (@maria)" in bot.telegram.last_text and "Tap a number, or type one." in bot.telegram.last_text
    await bot.send("200")
    assert await bot.services.db.get_limits() == {}


async def test_only_the_admin_can_type_limits(bot):
    await members(bot)
    await bot.press(f"lim:type:{EVERYONE}:a", user_id=MARIA)
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == ADMIN_ONLY


async def test_the_admin_sees_and_manages_someones_items(bot):
    await members(bot)
    db = bot.services.db
    tracker = await db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    digest = await db.create_digest(MARIA, "SKG", "europe", days_ahead=30)
    await bot.press(f"lim:who:{MARIA}")
    assert "Active right now</b>: 2" in bot.telegram.last_text
    await bot.press(f"lim:items:{MARIA}")
    to_admin = sent_to(bot, USER_ID)[-3:]
    assert "<b>Trackers and digests</b> of Maria (@maria)" in to_admin[0]["text"]
    assert "ATH" in to_admin[1]["text"] and "SKG" in to_admin[2]["text"]

    await bot.press(f"dash:pause:t:{tracker.id}")
    assert (await db.get_tracker(tracker.id)).status == PAUSED
    assert "The admin paused your Tracker #" in sent_to(bot, MARIA)[-1]["text"]

    await bot.press(f"dash:del:d:{digest.id}")
    assert await db.get_digest(digest.id) is None
    told = sent_to(bot, MARIA)[-1]
    assert "The admin deleted your Digest #" in told["text"] and "reply_markup" not in told


async def test_the_admin_isnt_held_to_someones_limit(bot):
    await members(bot)
    db = bot.services.db
    paused = await db.create_tracker(MARIA, "ATH", "ROM", future(4), 100.0)
    await db.set_tracker_status(paused.id, PAUSED)
    for day in (5, 6, 7):
        await db.create_tracker(MARIA, "ATH", "LON", future(day), 100.0)

    await bot.press(f"dash:resume:t:{paused.id}")
    assert (await db.get_tracker(paused.id)).status == ACTIVE
    assert "The admin resumed your Tracker #" in sent_to(bot, MARIA)[-1]["text"]


async def test_the_admin_can_edit_someones_tracker(bot):
    await members(bot)
    tracker = await bot.services.db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:budget")
    await bot.send("60")
    assert (await bot.services.db.get_tracker(tracker.id)).max_budget == 60.0
    await bot.press("edit:field:frequency")
    await bot.press("edit:freq:12")
    assert not sent_to(bot, MARIA)  # told once the admin stops editing, not per change
    assert bot.jobs("tell:") == [f"tell:t:{tracker.id}"]

    await run_jobs(bot, "tell:")
    told = sent_to(bot, MARIA)
    assert len(told) == 1 and "The admin changed your Tracker #" in told[0]["text"] and "€60" in told[0]["text"]


async def run_jobs(bot, prefix):
    for job in bot.app.job_queue.jobs():
        if job.name.startswith(prefix):
            await job.run(bot.app)
            job.schedule_removal()


async def test_an_edit_that_changes_nothing_tells_nobody(bot):
    await members(bot)
    tracker = await bot.services.db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:frequency")
    await bot.press(f"edit:freq:{tracker.frequency_hours}")
    assert bot.jobs("tell:") == []


async def test_editing_someones_budget_says_they_get_the_alert(bot):
    await members(bot)
    db = bot.services.db
    tracker = await db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await db.record_price(tracker.id, 80.0, "Aegean")
    await bot.press(f"dash:edit:t:{tracker.id}")
    await bot.press("edit:field:budget")
    await bot.send("90")
    assert "so they'll get an alert at the next check" in bot.telegram.last_text


async def test_someone_with_nothing_gets_a_short_note(bot):
    await members(bot)
    await bot.press(f"lim:items:{NIKOS}")
    assert bot.telegram.last_text == "📋 Nikos (@nikos) · ID <code>666</code> has no trackers or digests."


async def test_members_cant_open_someones_items(bot):
    await members(bot)
    await bot.press(f"lim:items:{NIKOS}", user_id=MARIA)
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == ADMIN_ONLY


async def test_limits_shortcuts_set_one_or_both(bot):
    await members(bot)
    db = bot.services.db
    await bot.send(f"/limits {MARIA} active 5 days 90")
    assert "✅ <b>Saved.</b>" in bot.telegram.last_text and "👤 Maria (@maria)" in bot.telegram.last_text
    assert await limits_for(db, MARIA) == Limits(5, 90)

    await bot.send(f"/limits {MARIA} DAYS 120")
    assert await limits_for(db, MARIA) == Limits(5, 120)
    await bot.send("/limits everyone active 4")
    assert await limits_for(db, NIKOS) == Limits(4, MEMBER_MAX_RANGE_DAYS)

    await bot.send(f"/limits {MARIA} reset")
    assert "Back to everyone's limits" in bot.telegram.last_text
    assert await limits_for(db, MARIA) == Limits(4, MEMBER_MAX_RANGE_DAYS)
    await bot.send("/limits everyone reset")
    assert await db.get_limits() == {}


async def test_limits_shortcut_opens_a_screen(bot):
    await members(bot)
    await bot.send(f"/limits {MARIA}")
    assert "👤 Maria (@maria)" in bot.telegram.last_text and "Saved" not in bot.telegram.last_text
    assert ("📋 Their Trackers & Digests", f"lim:items:{MARIA}") in bot.telegram.last_buttons()


async def test_limits_shortcuts_refuse_bad_input(bot):
    await members(bot)
    for command, reply in [
        ("/limits maria active 5", "Start with a person's ID or <code>everyone</code>"),
        ("/limits 999 active 5", "Nobody with ID <code>999</code> has access"),
        (f"/limits {USER_ID} active 5", "Your own limits are always the most"),
        (f"/limits {MARIA} active", "I couldn't read that"),
        (f"/limits {MARIA} active 5 active 6", "I couldn't read that"),
        (f"/limits {MARIA} weeks 5", "I couldn't read that"),
        (f"/limits {MARIA} active 0 days 400", "<code>active</code> must be from 1 to 20. <code>days</code> must be from 30 to 330."),
    ]:
        await bot.send(command)
        assert reply in bot.telegram.last_text, command
    assert await bot.services.db.get_limits() == {}

    await bot.send(f"/limits {MARIA} active 5", user_id=MARIA)
    assert bot.telegram.last_text == ADMIN_ONLY


async def test_mytracks_with_an_id_shows_someones_items(bot):
    await members(bot)
    await bot.services.db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await bot.send(f"/mytracks {MARIA}")
    to_admin = sent_to(bot, USER_ID)[-2:]
    assert "<b>Trackers and digests</b> of Maria (@maria)" in to_admin[0]["text"] and "ATH" in to_admin[1]["text"]

    await bot.send(f"/mytracks {NIKOS}")
    assert "has no trackers or digests" in bot.telegram.last_text
    await bot.send("/mytracks maria")
    assert "<code>/mytracks ID</code>" in bot.telegram.last_text
    await bot.send(f"/mytracks {USER_ID}")
    assert "You have no trackers or digests yet" in bot.telegram.last_text

    await bot.send(f"/mytracks {NIKOS}", user_id=MARIA)
    assert bot.telegram.last_text == "Only the bot's admin can see someone else's trackers and digests."


async def test_expired_items_cant_be_resumed_from_an_old_card(bot):
    await members(bot)
    db = bot.services.db
    tracker = await db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await db.set_tracker_status(tracker.id, EXPIRED)  # its card still has the Resume button from when it was paused
    await bot.press(f"dash:resume:t:{tracker.id}", user_id=MARIA)
    assert "has expired: its dates have passed" in bot.telegram.last_text
    assert (await db.get_tracker(tracker.id)).status == EXPIRED
    await bot.press(f"dash:pause:t:{tracker.id}")
    assert (await db.get_tracker(tracker.id)).status == EXPIRED
    assert not sent_to(bot, MARIA)


async def test_odd_digits_and_huge_ids_get_a_clear_answer(bot):
    await members(bot)
    await bot.press(f"lim:type:{MARIA}:a")
    await bot.send("²")
    assert "Type a whole number from 1 to 20" in bot.telegram.last_text
    await bot.send("/limits ²")
    assert "Start with a person's ID" in bot.telegram.last_text
    await bot.send(f"/limits {MARIA} active ²")
    assert "I couldn't read that" in bot.telegram.last_text
    for command in ("/mytracks ²", "/mytracks 99999999999999999999"):
        await bot.send(command)
        assert "<code>/mytracks ID</code>" in bot.telegram.last_text, command


async def test_leaving_the_screen_stops_the_typing(bot):
    await members(bot)
    await bot.press(f"lim:type:{MARIA}:a")
    await bot.press(f"lim:who:{NIKOS}")  # on another /limits message
    await bot.send("8")
    assert "That wizard was closed" in bot.telegram.last_text
    assert await bot.services.db.get_limits() == {}


async def test_tapping_the_value_that_applies_doesnt_pin_it(bot):
    await members(bot)
    await bot.press(f"lim:who:{MARIA}")
    await bot.press(f"lim:set:{MARIA}:a:{MEMBER_MAX_ACTIVE}")
    assert bot.telegram.calls_to("answerCallbackQuery")[-1]["text"] == f"It's already {MEMBER_MAX_ACTIVE}."
    await bot.send(f"/limits {MARIA} active {MEMBER_MAX_ACTIVE}")
    assert "Nothing changed" in bot.telegram.last_text
    assert await bot.services.db.get_limits() == {}

    await bot.send("/limits everyone active 6")
    assert await limits_for(bot.services.db, MARIA) == Limits(6, MEMBER_MAX_RANGE_DAYS)


async def test_people_without_access_arent_told(bot):
    await members(bot)
    db = bot.services.db
    tracker = await db.create_tracker(MARIA, "ATH", "LON", future(10), 100.0)
    await db.delete_user(MARIA)
    await bot.send(f"/mytracks {MARIA}")
    assert "They don't have access anymore" in sent_to(bot, USER_ID)[-2]["text"]
    await bot.press(f"dash:pause:t:{tracker.id}")
    assert (await db.get_tracker(tracker.id)).status == PAUSED
    assert not sent_to(bot, MARIA)


async def test_a_long_list_of_people_is_cut_short(bot):
    db = bot.services.db
    for uid in range(1000, 1035):
        await db.request_access(uid, None, f"Person {uid}")
        await db.set_user_status(uid, APPROVED)
    await bot.send("/limits")
    assert "…and 5 more: open them with <code>/limits ID</code>" in bot.telegram.last_text
    assert len(bot.telegram.last_text) < 4096
    assert len([data for _, data in bot.telegram.last_buttons() if data.startswith("lim:who:")]) == 31


async def test_long_lists_wait_when_telegram_says_to_slow_down():
    from telegram.error import RetryAfter
    from bot.handlers.dashboard import _send_paced

    class Bot:
        def __init__(self):
            self.sent, self.refusals = [], 1

        async def send_message(self, chat_id, text, reply_markup=None):
            if self.refusals:
                self.refusals -= 1
                raise RetryAfter(0)
            self.sent.append(text)

    class Ctx:
        bot = Bot()

    await _send_paced(Ctx, 1, "card")
    assert Ctx.bot.sent == ["card"]
