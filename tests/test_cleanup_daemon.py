import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from daemon.scheduler import run_daily_cleanup_job

@pytest.mark.asyncio
async def test_run_daily_cleanup_job():
    context = MagicMock()
    with patch("daemon.scheduler.db_manager") as db_mock:
        db_mock.purge_stale_trackers = AsyncMock(return_value={"expired": 2, "purged": 1})
        await run_daily_cleanup_job(context)
        db_mock.purge_stale_trackers.assert_called_once()
