import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.error import Forbidden, TelegramError
from daemon.scheduler import TrackerDaemonScheduler, register_active_trackers_on_startup
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

@pytest.mark.asyncio
async def test_scheduler_handles_forbidden_user_blocks_bot():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 5, "user_id": 104, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 250.0, "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=200.0, airline="Aegean")
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock(side_effect=Forbidden("Bot was blocked by the user"))

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=5, bot=bot_mock)

    db_mock.update_tracker_status.assert_called_with(5, "PAUSED")

@pytest.mark.asyncio
async def test_register_active_trackers_on_startup():
    db_mock = MagicMock()
    db_mock.get_active_trackers = AsyncMock(return_value=[
        {"id": 10, "frequency_hours": 6},
        {"id": 11, "frequency_hours": 12}
    ])
    provider_mock = MagicMock()

    app_mock = MagicMock()
    job_queue_mock = MagicMock()
    app_mock.job_queue = job_queue_mock

    registered = await register_active_trackers_on_startup(app_mock, db_mock, provider_mock)
    assert registered == 2
    assert job_queue_mock.run_repeating.call_count == 2

def test_schedule_and_unschedule_tracker_job():
    from daemon.scheduler import schedule_tracker_job, unschedule_tracker_job

    job_queue_mock = MagicMock()
    mock_job = MagicMock()
    job_queue_mock.get_jobs_by_name.return_value = [mock_job]

    schedule_tracker_job(job_queue_mock, tracker_id=99, frequency_hours=12)
    job_queue_mock.run_repeating.assert_called_once()
    assert job_queue_mock.run_repeating.call_args[1]["name"] == "tracker_job_99"
    assert mock_job.schedule_removal.call_count == 1

    unschedule_tracker_job(job_queue_mock, tracker_id=99)
    job_queue_mock.get_jobs_by_name.assert_called_with("tracker_job_99")
    assert mock_job.schedule_removal.call_count == 2

@pytest.mark.asyncio
async def test_scheduler_polls_with_direct_only_flag():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 50, "user_id": 100, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 200.0, "direct_only": 1,
        "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=180.0, airline="Aegean", is_direct=True)
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=50, bot=bot_mock)

    provider_mock.search_flights.assert_called_once_with(
        origin="ATH", destination="LON", departure_date="2026-08-15", direct_only=True
    )


@pytest.mark.asyncio
async def test_scheduler_alert_includes_flight_times():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 60, "user_id": 100, "origin_code": "SKG", "destination_code": "ORY",
        "departure_date": "2027-04-03", "max_budget": 100.0, "direct_only": 1,
        "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("SKG", "ORY", "2027-04-03", price=85.0, airline="Transavia", is_direct=True, departure_time="17:45", arrival_time="19:55")
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=60, bot=bot_mock)

    bot_mock.send_message.assert_called_once()
    msg_text = bot_mock.send_message.call_args[1]["text"]
    assert "17:45" in msg_text
    assert "19:55" in msg_text




