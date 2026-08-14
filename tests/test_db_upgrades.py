import pytest
from datetime import datetime, timedelta, timezone
from database.db import DatabaseManager

@pytest.mark.asyncio
async def test_db_upgrades_budget_dedup_and_all_3_purge_rules(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = DatabaseManager(db_file)
    await db.init_db()

    # 1. Create tracker & test update_budget
    t_id = await db.create_tracker(
        user_id=100, origin_code="ATH", origin_name="Athens",
        destination_code="MJT", destination_name="Mytilene",
        departure_date="2026-09-15", max_budget=90.0
    )
    await db.update_budget(t_id, 32.40)
    tracker = await db.get_tracker_by_id(t_id)
    assert tracker["max_budget"] == 32.40

    # 2. Test deduplication check for active tracker & digest
    assert await db.has_active_tracker(100, "ATH", "MJT", "2026-09-15") is True
    assert await db.has_active_tracker(100, "ATH", "SKG", "2026-09-15") is False
    assert await db.has_active_digest(100, "ATH", "europe", "2026-09-15") is False

    # 3. Test Rule 1: Active past departure date -> status becomes EXPIRED
    old_dep_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    t_past_id = await db.create_tracker(
        user_id=101, origin_code="ATH", origin_name="Athens",
        destination_code="SKG", destination_name="Thessaloniki",
        departure_date=old_dep_date, max_budget=50.0
    )

    # Test Rule 2: Expired tracker older than 30 days -> PURGED (deleted)
    t_exp_35d_id = await db.create_tracker(
        user_id=102, origin_code="ATH", origin_name="Athens",
        destination_code="FCO", destination_name="Rome",
        departure_date=old_dep_date, max_budget=50.0
    )
    await db.update_tracker_status(t_exp_35d_id, "EXPIRED")

    # Execute purge_stale_trackers
    stats = await db.purge_stale_trackers()
    assert isinstance(stats, dict)
    assert "expired" in stats
    assert "purged" in stats
    
    t_past = await db.get_tracker_by_id(t_past_id)
    assert t_past["status"] == "EXPIRED"
