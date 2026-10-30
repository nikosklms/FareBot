import aiosqlite

from database.models import ACTIVE, EXPIRED, PAUSED
from tests.fakes import future


async def make_tracker(db, user_id=1, origin="ATH", destination="LON", start=None, **kwargs):
    return await db.create_tracker(user_id=user_id, origin_code=origin, destination_code=destination,
                                   departure_date=start or future(30), max_budget=kwargs.pop("max_budget", 100.0),
                                   **kwargs)


async def test_create_and_read_tracker(db):
    tracker = await make_tracker(db, start=future(10), departure_date_end=future(15), direct_only=True)

    assert tracker.id > 0
    assert tracker.status == ACTIVE
    assert tracker.direct_only is True
    assert tracker.departure_date_end == future(15)
    assert tracker.last_departure_date == future(15)
    assert await db.get_tracker(tracker.id) == tracker
    assert await db.list_trackers(1) == [tracker]
    assert await db.active_trackers() == [tracker]


async def test_find_tracker_matches_active_or_paused_only(db):
    tracker = await make_tracker(db, start=future(10))
    assert (await db.find_tracker(1, "ATH", "LON", future(10))).id == tracker.id
    assert await db.find_tracker(1, "ATH", "LON", future(11)) is None
    assert await db.find_tracker(2, "ATH", "LON", future(10)) is None

    await db.set_tracker_status(tracker.id, PAUSED)
    assert await db.find_tracker(1, "ATH", "LON", future(10)) is not None
    await db.set_tracker_status(tracker.id, EXPIRED)
    assert await db.find_tracker(1, "ATH", "LON", future(10)) is None


async def test_record_price_and_failures(db):
    tracker = await make_tracker(db)
    assert await db.record_failure(tracker.id) == 1
    assert await db.record_failure(tracker.id) == 2

    await db.record_price(tracker.id, 80.0, "Aegean")
    updated = await db.get_tracker(tracker.id)
    assert updated.last_price_found == 80.0
    assert updated.consecutive_failures == 0
    assert updated.last_checked_at is not None


async def test_delete_tracker_removes_price_history(db):
    tracker = await make_tracker(db)
    await db.record_price(tracker.id, 80.0, "Aegean")
    await db.delete_tracker(tracker.id)

    assert await db.get_tracker(tracker.id) is None
    async with aiosqlite.connect(db.path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM price_history") as cur:
            assert (await cur.fetchone())[0] == 0


async def test_digest_crud_and_find(db):
    rolling = await db.create_digest(user_id=1, origin_code="ATH", region="europe", days_ahead=30,
                                     delivery_day="Friday", delivery_time="18:00")
    fixed = await db.create_digest(user_id=1, origin_code="ATH", region="europe", max_budget=80.0,
                                   departure_date=future(10), departure_date_end=future(20))

    assert rolling.max_budget is None and rolling.days_ahead == 30
    assert (await db.find_digest(1, "ATH", "europe", 30, None, None)).id == rolling.id
    assert (await db.find_digest(1, "ATH", "europe", None, future(10), future(20))).id == fixed.id
    assert await db.find_digest(1, "ATH", "europe", 60, None, None) is None

    updated = await db.update_digest(rolling.id, max_budget=50.0, delivery_time="09:30")
    await db.set_digest_status(rolling.id, PAUSED)
    assert (updated.max_budget, updated.delivery_time) == (50.0, "09:30")
    assert (await db.get_digest(rolling.id)).status == PAUSED
    assert [d.id for d in await db.active_digests()] == [fixed.id]

    await db.delete_digest(fixed.id)
    assert [d.id for d in await db.list_digests(1)] == [rolling.id]


async def test_count_active_includes_trackers_and_digests(db):
    await make_tracker(db)
    paused = await make_tracker(db, destination="PAR")
    await db.set_tracker_status(paused.id, PAUSED)
    await db.create_digest(user_id=1, origin_code="ATH", region="asia", days_ahead=30)

    assert await db.count_active(1) == 2
    assert await db.count_active(2) == 0


async def test_digest_window_rolling_and_fixed(db):
    from datetime import date
    rolling = await db.create_digest(user_id=1, origin_code="ATH", region="europe", days_ahead=7)
    fixed = await db.create_digest(user_id=1, origin_code="ATH", region="asia", departure_date="2027-01-05")

    assert rolling.window(date(2027, 1, 1)) == ("2027-01-02", "2027-01-08")
    assert fixed.window(date(2027, 1, 1)) == ("2027-01-05", None)


async def test_purge_stale_expires_by_travel_date_and_keeps_paused_future_items(db):
    from datetime import date, timedelta
    today = date.today()
    long_ago = (today - timedelta(days=45)).isoformat()
    past = (await make_tracker(db, start=(today - timedelta(days=2)).isoformat())).id
    paused_past = (await make_tracker(db, destination="PAR", start=(today - timedelta(days=3)).isoformat())).id
    await db.set_tracker_status(paused_past, PAUSED)
    range_still_open = (await make_tracker(db, start=long_ago, departure_date_end=future(5))).id
    old_paused_future = (await make_tracker(db, destination="ROM", start=future(90))).id
    await db.set_tracker_status(old_paused_future, PAUSED)
    long_expired = (await make_tracker(db, destination="MAD", start=long_ago)).id
    await db.set_tracker_status(long_expired, EXPIRED)
    past_digest = (await db.create_digest(user_id=1, origin_code="ATH", region="asia", departure_date=long_ago)).id
    rolling_digest = (await db.create_digest(user_id=1, origin_code="ATH", region="europe", days_ahead=30)).id
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("UPDATE trackers SET created_at = '2000-01-01'")
        await conn.execute("UPDATE digests SET created_at = '2000-01-01'")
        await conn.commit()

    result = await db.purge_stale(today)

    assert {t.id for t in result.expired_trackers} == {past, paused_past}
    assert [d.id for d in result.expired_digests] == [past_digest]
    assert (await db.get_tracker(past)).status == EXPIRED
    assert (await db.get_tracker(range_still_open)).status == ACTIVE
    assert (await db.get_tracker(old_paused_future)).status == PAUSED  # old but still wanted: kept
    assert await db.get_tracker(long_expired) is None  # travel dates over 30 days ago
    assert (await db.get_digest(rolling_digest)).status == ACTIVE
    assert result.purged == 2  # long_expired and past_digest (expired now, dates 45 days ago)


async def test_log_unauthorized_attempt(db):
    await db.log_unauthorized_attempt(77, "@intruder", "Joe", "/search")
    async with aiosqlite.connect(db.path) as conn:
        async with conn.execute("SELECT user_id, username, input_text FROM unauthorized_attempts") as cur:
            assert await cur.fetchall() == [(77, "@intruder", "/search")]


async def test_update_tracker_fields_and_rejects_unknown_ones(db):
    import pytest
    tracker = await make_tracker(db)
    updated = await db.update_tracker(tracker.id, departure_date=future(40), departure_date_end=future(45),
                                      direct_only=True, frequency_hours=24, max_budget=55.5)
    assert (updated.departure_date, updated.departure_date_end) == (future(40), future(45))
    assert (updated.direct_only, updated.frequency_hours, updated.max_budget) == (True, 24, 55.5)
    with pytest.raises(ValueError):
        await db.update_tracker(tracker.id, user_id=999)
    with pytest.raises(ValueError):
        await db.update_digest(tracker.id, origin_code="SKG")
