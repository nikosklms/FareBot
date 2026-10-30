from datetime import timezone

from database.models import ACTIVE, EXPIRED, PAUSED
from daemon.scheduler import check_tracker, register_jobs, schedule_digest, send_digest
from providers.base import FlightOffer
from tests.fakes import USER_ID, future


def offers_at(*prices, **extra):
    def offers(origin, destination, day):
        return [FlightOffer(origin, destination, day, price=p, airline=f"Air{i}", **extra) for i, p in enumerate(prices)]
    return offers


async def tracker(bot, start=None, end=None, budget=100.0, direct_only=False):
    return await bot.services.db.create_tracker(USER_ID, "ATH", "LON", start or future(10), budget,
                                                departure_date_end=end, direct_only=direct_only)


async def test_price_under_budget_sends_alert_and_pauses(bot, provider):
    provider.offers = offers_at(130.0, 90.0, 95.0, 99.0, 120.0, 140.0, departure_time="08:00", arrival_time="10:30")
    t = await tracker(bot)

    assert await check_tracker(bot.services, bot.app.bot, t.id) is False

    updated = await bot.services.db.get_tracker(t.id)
    assert (updated.status, updated.last_price_found) == (PAUSED, 90.0)
    alert = bot.telegram.last_text
    assert "PRICE DROP ALERT" in alert and "Top 5 offers" in alert
    assert alert.index("€90.00") < alert.index("€95.00") and "€140.00" not in alert
    assert "08:00 ➔ 10:30" in alert
    assert bot.telegram.button_data("Set Lower Budget") == f"dash:budget:t:{t.id}"
    assert bot.telegram.button_data("Delete") == f"dash:del:t:{t.id}"


async def test_price_over_budget_keeps_polling_quietly(bot, provider):
    provider.offers = offers_at(150.0)
    t = await tracker(bot)
    assert await check_tracker(bot.services, bot.app.bot, t.id) is True
    assert (await bot.services.db.get_tracker(t.id)).last_price_found == 150.0
    assert bot.telegram.calls_to("sendMessage") == []


async def test_range_and_direct_only_are_used(bot, provider):
    provider.offers = offers_at(150.0)
    t = await tracker(bot, start=future(10), end=future(12), direct_only=True)
    await check_tracker(bot.services, bot.app.bot, t.id)
    assert sorted(provider.queries) == [("ATH", "LON", future(d), True) for d in (10, 11, 12)]


async def test_repeated_failures_pause_tracker(bot, provider):
    t = await tracker(bot)
    assert await check_tracker(bot.services, bot.app.bot, t.id) is True
    assert await check_tracker(bot.services, bot.app.bot, t.id) is True
    assert await check_tracker(bot.services, bot.app.bot, t.id) is False
    assert (await bot.services.db.get_tracker(t.id)).status == PAUSED
    assert "after 3 attempts" in bot.telegram.last_text


async def test_past_departure_expires(bot):
    t = await tracker(bot, start="2020-01-01")
    assert await check_tracker(bot.services, bot.app.bot, t.id) is False
    assert (await bot.services.db.get_tracker(t.id)).status == EXPIRED
    assert "expired" in bot.telegram.last_text


async def test_inactive_tracker_is_not_checked(bot, provider):
    t = await tracker(bot)
    await bot.services.db.set_tracker_status(t.id, PAUSED)
    assert await check_tracker(bot.services, bot.app.bot, t.id) is False
    assert provider.queries == []


async def test_blocked_user_pauses_tracker(bot, provider):
    provider.offers = offers_at(50.0)
    bot.telegram.blocked_chats.add(USER_ID)
    t = await tracker(bot)
    await check_tracker(bot.services, bot.app.bot, t.id)
    assert (await bot.services.db.get_tracker(t.id)).status == PAUSED


async def test_send_digest_report(bot, provider):
    provider.offers = offers_at(40.0, typical_min=90.0, typical_max=110.0)
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "oceania", days_ahead=2, max_results=3)

    assert await send_digest(bot.services, bot.app.bot, digest.id) is True

    texts = bot.telegram.texts
    assert "Searching deals for next 2 days" in texts[0]
    assert "Weekly Flight Digest: ATH → Oceania" in texts[-1]
    assert "BIGGEST DISCOUNTS" in texts[-1] and "CHEAPEST FLIGHTS" in texts[-1]
    assert {day for _, _, day, _ in provider.queries} == {future(1), future(2)}


async def test_digest_with_no_deals(bot):
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "oceania", days_ahead=1, max_budget=10.0)
    assert await send_digest(bot.services, bot.app.bot, digest.id) is True
    assert "No deals found this week (budget: €10.00)" in bot.telegram.last_text


async def test_digest_with_past_fixed_dates_expires(bot, provider):
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "europe", departure_date="2020-01-01")
    assert await send_digest(bot.services, bot.app.bot, digest.id) is False
    assert (await bot.services.db.get_digest(digest.id)).status == EXPIRED
    assert provider.queries == []


async def test_register_jobs_schedules_everything(bot):
    db = bot.services.db
    first = await tracker(bot)
    second = await tracker(bot, start=future(20))
    paused = await tracker(bot, start=future(30))
    await db.set_tracker_status(paused.id, PAUSED)
    digest = await db.create_digest(USER_ID, "ATH", "europe", days_ahead=30, delivery_day="Monday", delivery_time="09:30")

    bot.services.timezone = timezone.utc
    await register_jobs(bot.app)

    assert sorted(bot.jobs()) == sorted([f"tracker_job_{first.id}", f"tracker_job_{second.id}",
                                         f"digest_job_{digest.id}", "daily_cleanup"])
    [digest_job] = bot.app.job_queue.get_jobs_by_name(f"digest_job_{digest.id}")
    assert "day_of_week='mon'" in str(digest_job.job.trigger)
    assert (await db.get_tracker(first.id)).status == ACTIVE


async def test_digest_report_has_collapsible_track_buttons(bot, provider):
    provider.offers = offers_at(40.0, typical_min=90.0, typical_max=110.0)
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "oceania", days_ahead=1, max_results=2)

    await send_digest(bot.services, bot.app.bot, digest.id, bot.user_data)
    assert bot.telegram.last_buttons() == [("🔔 Track a deal", "deals:show")]

    report_message = bot.telegram.last_message_id
    await bot.press("deals:show", message_id=report_message)
    first_deal = bot.telegram.button_data("Track #1")
    assert first_deal.startswith("trk:add:ATH:") and first_deal.endswith(":36.00:0")

    await bot.press(first_deal)
    [tracker] = await bot.services.db.list_trackers(USER_ID)
    assert tracker.max_budget == 36.0
    assert "Tracking started" in bot.telegram.last_text


async def test_digest_job_runs_with_the_users_data(bot):
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "europe", days_ahead=30)
    schedule_digest(bot.app.job_queue, digest, timezone.utc)
    [job] = bot.app.job_queue.get_jobs_by_name(f"digest_job_{digest.id}")
    assert job.user_id == USER_ID and job.chat_id == USER_ID
