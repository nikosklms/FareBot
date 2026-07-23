import pytest
from database.db import DatabaseManager

@pytest.mark.asyncio
async def test_db_create_tracker_with_departure_date_end(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = DatabaseManager(db_file)
    await db.init_db()

    t_id = await db.create_tracker(
        user_id=123,
        origin_code="ATH",
        origin_name="Athens",
        destination_code="LON",
        destination_name="London",
        departure_date="2026-09-01",
        departure_date_end="2026-09-15",
        max_budget=200.0,
        currency="EUR",
        frequency_hours=6,
        direct_only=1
    )

    tracker = await db.get_tracker_by_id(t_id)
    assert tracker["departure_date"] == "2026-09-01"
    assert tracker["departure_date_end"] == "2026-09-15"
