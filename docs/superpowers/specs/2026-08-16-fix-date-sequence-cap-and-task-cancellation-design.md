# Fix Date Sequence 60-Day Cap & Implement Real Explore Task Cancellation Design

## Root Cause Analysis

### Bug 1: 90 Days capped at 60 Days
- **Location**: `utils/date_parser.py` line 33: `def generate_date_sequence(start_date: str, end_date: str, max_days: Optional[int] = 60)`.
- **Root Cause**: `generate_date_sequence` defaulted `max_days` to 60. Whenever a 90-day range (`2026-08-17..2026-11-14`) was processed, `generate_date_sequence` broke out after 60 days, truncating 90-day queries to 60 days.
- **Fix**: Remove the artificial 60-day cap in `generate_date_sequence` (or increase `max_days` default to 330 to match max wizard horizon limit).

### Bug 2: Cancel button didn't stop running search task
- **Location**: `bot/handlers/common.py` (`cancel_callback`) and `bot/handlers/explore.py` (`_execute_wizard_explore`).
- **Root Cause**: Tapping `❌ Cancel` edited the Telegram message text to `❌ Action cancelled.`, but the background `asyncio.Task` running `run_explore_query` continued making HTTP requests and subsequently overwrote the message with its next `status_cb` call.
- **Fix**:
  1. Store the active execution task in `context.user_data["active_explore_task"] = asyncio.current_task()`.
  2. In `cancel_callback` in `common.py`, check for `active_explore_task` in `context.user_data`, call `task.cancel()`, edit the message to `❌ Search cancelled.`, and catch `asyncio.CancelledError` in `run_explore_query` / `_execute_wizard_explore`.

## Verification Plan
- Unit test `generate_date_sequence` with 90-day range returns 90 dates.
- Unit test canceling an active explore task aborts execution cleanly.
- Run full pytest test suite to ensure 100% pass rate.
