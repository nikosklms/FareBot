import pytest
import os
import tempfile
from database.db import DatabaseManager

@pytest.mark.asyncio
async def test_db_init_and_tracker_crud():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        count = await db.get_active_trackers_count(12345)
        assert count == 0

        tracker_id = await db.create_tracker(
            user_id=12345,
            origin_code="ATH",
            origin_name="Athens Intl",
            destination_code="LON",
            destination_name="London All",
            departure_date="2026-08-15",
            max_budget=250.0
        )
        assert tracker_id > 0

        count = await db.get_active_trackers_count(12345)
        assert count == 1

        active = await db.get_active_trackers()
        assert len(active) == 1
        assert active[0]["origin_code"] == "ATH"
        assert active[0]["max_budget"] == 250.0

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

@pytest.mark.asyncio
async def test_db_tracker_status_and_failures():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        t_id = await db.create_tracker(
            user_id=100, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-08-15", max_budget=300.0
        )

        # Test failure increment
        fails = await db.increment_failure_count(t_id)
        assert fails == 1
        fails = await db.increment_failure_count(t_id)
        assert fails == 2

        # Test reset failure
        await db.reset_failure_count(t_id)
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["consecutive_failures"] == 0

        # Test update status
        await db.update_tracker_status(t_id, "PAUSED")
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["status"] == "PAUSED"

        # Test log price
        await db.log_price(t_id, 280.0, "Aegean")
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["last_price_found"] == 280.0

        # Test user trackers list
        user_trackers = await db.get_user_trackers(100)
        assert len(user_trackers) == 1

        # Test expired query
        expired = await db.get_expired_trackers("2026-09-01")
        assert len(expired) == 0  # Departure date is 2026-08-15, which is < 2026-09-01, but status is PAUSED!

        await db.update_tracker_status(t_id, "ACTIVE")
        expired = await db.get_expired_trackers("2026-09-01")
        assert len(expired) == 1

        # Test delete tracker
        await db.delete_tracker(t_id)
        user_trackers = await db.get_user_trackers(100)
        assert len(user_trackers) == 0

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
