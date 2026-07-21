import pytest
from unittest.mock import AsyncMock, MagicMock
from daemon.scheduler import TrackerDaemonScheduler
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_scheduler_check_price_match():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 1, "user_id": 100, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 200.0, "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=180.0, airline="Aegean")
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=1, bot=bot_mock)

    db_mock.log_price.assert_called_once_with(1, 180.0, "Aegean")
    db_mock.update_tracker_status.assert_called_once_with(1, "PAUSED")
    bot_mock.send_message.assert_called_once()
