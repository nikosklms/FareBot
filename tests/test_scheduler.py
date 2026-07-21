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

@pytest.mark.asyncio
async def test_scheduler_3_failures_triggers_pause():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 2, "user_id": 101, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 200.0, "consecutive_failures": 2, "status": "ACTIVE"
    })
    db_mock.increment_failure_count = AsyncMock(return_value=3)
    db_mock.update_tracker_status = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=2, bot=bot_mock)

    db_mock.increment_failure_count.assert_called_once_with(2)
    db_mock.update_tracker_status.assert_called_once_with(2, "PAUSED")
    bot_mock.send_message.assert_called_once()
    assert "3 attempts" in bot_mock.send_message.call_args[1]["text"]

@pytest.mark.asyncio
async def test_scheduler_past_departure_date_expires():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 3, "user_id": 102, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2020-01-01", "max_budget": 200.0, "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.update_tracker_status = AsyncMock()

    provider_mock = MagicMock()
    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=3, bot=bot_mock)

    db_mock.update_tracker_status.assert_called_once_with(3, "EXPIRED")
    bot_mock.send_message.assert_called_once()
    assert "expired" in bot_mock.send_message.call_args[1]["text"].lower()

@pytest.mark.asyncio
async def test_scheduler_notification_button_payloads():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 4, "user_id": 103, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 250.0, "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=210.0, airline="British Airways", booking_url="http://test.url")
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=4, bot=bot_mock)

    bot_mock.send_message.assert_called_once()
    kwargs = bot_mock.send_message.call_args[1]
    reply_markup = kwargs["reply_markup"]
    assert reply_markup is not None
    inline_keyboard = reply_markup.inline_keyboard
    assert len(inline_keyboard) == 2
    assert inline_keyboard[0][0].url == "http://test.url"
    assert "dash_pause_4" in inline_keyboard[1][0].callback_data
    assert "dash_del_4" in inline_keyboard[1][1].callback_data
