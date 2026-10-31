"""Everyone except the admin gets 3 active trackers and digests and date ranges of up to 180 days."""
from bot.handlers.share import share_payload
from config import MAX_TRACKERS_PER_USER, MEMBER_MAX_ACTIVE, MEMBER_MAX_RANGE_DAYS
from database.models import APPROVED
from tests.fakes import USER_ID, future
from tests.test_share import digest, tracker

MARIA = 555


async def member(bot):
    await bot.services.db.request_access(MARIA, "@maria", "Maria")
    await bot.services.db.set_user_status(MARIA, APPROVED)


async def finish_search(bot, user_id):
    task = bot.app.user_data[user_id].get("running_task")
    if task:
        await task


async def test_members_can_search_up_to_180_days(bot, provider):
    await member(bot)
    await bot.send(f"/search ATH LON {future(1)}..{future(181)}", user_id=MARIA)
    assert "the most you can search is 180 days" in bot.telegram.last_text
    assert not provider.queries

    await bot.send(f"/search ATH LON {future(1)}..{future(180)}", user_id=MARIA)
    await finish_search(bot, MARIA)
    assert len({day for _, _, day, _ in provider.queries}) == 180


async def test_the_admin_can_search_longer_ranges(bot, provider):
    await bot.send(f"/search ATH LON {future(1)}..{future(200)}")
    await finish_search(bot, USER_ID)
    assert len({day for _, _, day, _ in provider.queries}) == 200


async def test_members_days_ahead_are_limited_in_shortcuts_and_wizards(bot):
    await member(bot)
    await bot.send("/explore ATH europe 181", user_id=MARIA)
    assert "between 1 and 180" in bot.telegram.last_text
    await bot.send("/digest ATH europe 181", user_id=MARIA)
    assert "between 1 and 180" in bot.telegram.last_text

    await bot.send("/explore", user_id=MARIA)
    await bot.send("ATH", user_id=MARIA)
    await bot.press("exp:org:ATH", user_id=MARIA)
    await bot.press("exp:reg:europe", user_id=MARIA)
    await bot.press("exp:sort:price", user_id=MARIA)
    await bot.send("200", user_id=MARIA)
    assert "between 1 and 180" in bot.telegram.last_text


async def test_members_can_have_3_active_trackers_and_digests(bot):
    await member(bot)
    db = bot.services.db
    await db.create_digest(MARIA, "ATH", "europe", days_ahead=30)
    for day in (5, 6):
        await bot.send(f"/track ATH LON {future(day)} 100", user_id=MARIA)
    assert await db.count_active(MARIA) == MEMBER_MAX_ACTIVE

    await bot.send(f"/track ATH PAR {future(5)} 100", user_id=MARIA)
    assert "already have 3 active trackers and digests" in bot.telegram.last_text
    await bot.send("/digest ATH asia 30", user_id=MARIA)
    assert "already have 3 active trackers and digests" in bot.telegram.last_text
    assert await db.count_active(MARIA) == MEMBER_MAX_ACTIVE


async def test_a_member_cant_resume_past_the_limit(bot):
    await member(bot)
    db = bot.services.db
    paused = await db.create_tracker(MARIA, "ATH", "ROM", future(4), 100.0)
    await db.set_tracker_status(paused.id, "PAUSED")
    for day in (5, 6, 7):
        await db.create_tracker(MARIA, "ATH", "LON", future(day), 100.0)

    await bot.press(f"dash:resume:t:{paused.id}", user_id=MARIA)
    assert "already have 3 active trackers and digests" in bot.telegram.last_text
    assert (await db.get_tracker(paused.id)).status == "PAUSED"


async def test_the_admin_keeps_the_higher_limit(bot):
    db = bot.services.db
    for day in range(MEMBER_MAX_ACTIVE + 1):
        await db.create_tracker(USER_ID, "ATH", "LON", future(10 + day), 100.0)
    await bot.send(f"/track ATH PAR {future(5)} 100")
    assert "Tracking started" in bot.telegram.last_text
    assert await db.count_active(USER_ID) == MEMBER_MAX_ACTIVE + 2


async def test_shared_items_are_checked_against_the_recipients_limit(bot):
    await member(bot)
    long_tracker = share_payload(tracker(departure_date=future(10), departure_date_end=future(200)))
    await bot.send(f"/start {long_tracker}", user_id=MARIA)
    assert "covers more than 180 days, the most you can search" in bot.telegram.last_text
    await bot.press(f"sh:add:{long_tracker}", user_id=MARIA)
    assert await bot.services.db.count_active(MARIA) == 0

    far_digest = share_payload(digest(days_ahead=200, departure_date=None, departure_date_end=None))
    await bot.send(f"/start {far_digest}", user_id=MARIA)
    assert "covers more than 180 days" in bot.telegram.last_text

    await bot.send(f"/start {long_tracker}")  # the admin can add it
    assert "Add it to your account?" in bot.telegram.last_text


async def test_help_shows_each_users_own_limit(bot):
    await member(bot)
    await bot.send("/help", user_id=MARIA)
    assert f"(up to {MEMBER_MAX_ACTIVE} active)" in bot.telegram.last_text
    await bot.send("/help")
    assert f"(up to {MAX_TRACKERS_PER_USER} active)" in bot.telegram.last_text


def test_member_limits_are_lower_than_the_admins():
    assert MEMBER_MAX_RANGE_DAYS == 180 and MEMBER_MAX_ACTIVE == 3 < MAX_TRACKERS_PER_USER
