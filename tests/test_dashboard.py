from database.models import ACTIVE, APPROVED, PAUSED
from tests.fakes import USER_ID, future

OTHER_USER = 456


async def make_tracker(bot, user_id=USER_ID):
    return await bot.services.db.create_tracker(user_id, "ATH", "LON", future(10), 100.0)


async def make_digest(bot):
    return await bot.services.db.create_digest(USER_ID, "ATH", "europe", days_ahead=30, delivery_day="Friday",
                                               delivery_time="18:00")


async def test_mytracks_empty(bot):
    await bot.send("/mytracks")
    assert "no trackers or digests" in bot.telegram.last_text


async def test_mytracks_lists_trackers_and_digests(bot):
    tracker = await make_tracker(bot)
    digest = await make_digest(bot)
    await bot.send("/mytracks")

    tracker_msg, digest_msg = bot.telegram.calls_to("sendMessage")[-2:]
    assert f"Tracker #{tracker.id}" in tracker_msg["text"]
    assert f"Weekly Digest #{digest.id}" in digest_msg["text"] and "every Friday at 18:00" in digest_msg["text"]
    assert bot.telegram.button_data("Pause") == f"dash:pause:d:{digest.id}"


async def test_pause_and_resume_tracker(bot):
    tracker = await make_tracker(bot)
    await bot.press(f"dash:pause:t:{tracker.id}")
    assert (await bot.services.db.get_tracker(tracker.id)).status == PAUSED
    assert bot.telegram.button_data("Resume") == f"dash:resume:t:{tracker.id}"

    await bot.press(f"dash:resume:t:{tracker.id}")
    assert (await bot.services.db.get_tracker(tracker.id)).status == ACTIVE
    assert bot.jobs("tracker_job_") == [f"tracker_job_{tracker.id}"]


async def test_resuming_digest_keeps_its_schedule(bot):
    digest = await make_digest(bot)
    await bot.press(f"dash:pause:d:{digest.id}")
    assert bot.jobs("digest_job_") == []
    await bot.press(f"dash:resume:d:{digest.id}")

    [job] = bot.app.job_queue.get_jobs_by_name(f"digest_job_{digest.id}")
    trigger = str(job.job.trigger)
    assert "day_of_week='fri'" in trigger and "hour='18'" in trigger and "minute='0'" in trigger


async def test_delete(bot):
    tracker = await make_tracker(bot)
    digest = await make_digest(bot)
    await bot.press(f"dash:del:t:{tracker.id}")
    await bot.press(f"dash:del:d:{digest.id}")
    assert await bot.services.db.list_trackers(USER_ID) == []
    assert await bot.services.db.list_digests(USER_ID) == []
    assert "Digest" in bot.telegram.last_text and "deleted" in bot.telegram.last_text


async def test_members_cannot_touch_other_users_items(bot):
    await bot.services.db.request_access(OTHER_USER, None, "Other")
    await bot.services.db.set_user_status(OTHER_USER, APPROVED)
    tracker = await make_tracker(bot)  # the admin's
    await bot.press(f"dash:del:t:{tracker.id}", user_id=OTHER_USER)
    assert bot.telegram.alerts[-1] == "This item no longer exists."
    assert await bot.services.db.get_tracker(tracker.id) is not None


async def test_resume_resets_failures_and_respects_the_limit(bot):
    from config import MAX_TRACKERS_PER_USER
    db = bot.services.db
    tracker = await make_tracker(bot)
    for _ in range(3):
        await db.record_failure(tracker.id)
    await db.set_tracker_status(tracker.id, PAUSED)
    await bot.press(f"dash:resume:t:{tracker.id}")
    assert (await db.get_tracker(tracker.id)).consecutive_failures == 0

    await bot.press(f"dash:pause:t:{tracker.id}")
    for i in range(MAX_TRACKERS_PER_USER):
        await db.create_tracker(USER_ID, "ATH", "PAR", future(20 + i), 100.0)
    await bot.press(f"dash:resume:t:{tracker.id}")
    assert "already have" in bot.telegram.last_text
    assert (await db.get_tracker(tracker.id)).status == PAUSED
