import pytest
import os
import tempfile
from database.db import DatabaseManager
from providers.fast_flights import FastFlightsProvider
from daemon.scheduler import TrackerDaemonScheduler

@pytest.mark.asyncio
async def test_full_system_wiring():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        provider = FastFlightsProvider()
        scheduler = TrackerDaemonScheduler(db, provider)

        t_id = await db.create_tracker(
            user_id=555, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-12-01", max_budget=200.0
        )
        assert t_id > 0

        active = await db.get_active_trackers()
        assert len(active) == 1
        assert active[0]["user_id"] == 555
        assert active[0]["origin_code"] == "ATH"

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

@pytest.mark.asyncio
async def test_full_system_direct_tracker_creation():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        t_id = await db.create_tracker(
            user_id=777, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-09-01", max_budget=180.0, direct_only=1
        )

        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["direct_only"] == 1
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

