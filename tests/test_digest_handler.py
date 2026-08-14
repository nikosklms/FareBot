import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.digest import digest_command
from daemon.scheduler import schedule_digest_job, run_digest_weekly_job

@pytest.mark.asyncio
async def test_digest_command_registration_and_schedule_job():
    # 1. Test digest_command with default Sunday@15:00 and custom schedule
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.job_queue = MagicMock()
    context.args = ["ATH", "europe", "80"]  # No schedule arg -> default Sunday@15:00

    with patch("bot.handlers.auth.get_allowed_users", return_value=[123]):
        with patch("bot.handlers.digest.db_manager") as db_mock:
            db_mock.has_active_digest = AsyncMock(return_value=False)
            db_mock.create_tracker = AsyncMock(return_value=1)
            await digest_command(update, context)
            update.message.reply_text.assert_called_once()
            assert "Sunday at 15:00" in update.message.reply_text.call_args[0][0]

    # 2. Test schedule_digest_job registers with job_queue
    jq_mock = MagicMock()
    schedule_digest_job(jq_mock, tracker_id=1, user_id=123, origin="ATH", region="europe", budget=80.0, schedule_str="Sunday@15:00")
    assert jq_mock.run_daily.called or jq_mock.run_repeating.called

    # 3. Test weekly execution job runner
    job_context = MagicMock()
    job_context.job.data = {"user_id": 123, "origin": "ATH", "region": "europe", "budget": 80.0}
    with patch("services.explore_engine.run_explore_query") as explore_mock:
        explore_mock.return_value = [{
            "origin_code": "ATH",
            "destination_code": "CDG",
            "destination_name": "Paris CDG",
            "departure_date": "2026-09-15",
            "price": 50.0,
            "airline": "Air France",
            "discount_pct": 66.7
        }]
        await run_digest_weekly_job(job_context)
        explore_mock.assert_called_once()
