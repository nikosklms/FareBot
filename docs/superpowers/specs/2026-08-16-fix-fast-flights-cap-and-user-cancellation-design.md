# Fix FastFlights Range Cap & Global User Cancellation Design

## Root Cause Analysis

### Bug 1: 90 Days capped at 60 Days in `providers/fast_flights.py`
- **Location**: `providers/fast_flights.py` line 367: `max_days: Optional[int] = 60`.
- **Root Cause**: `search_flights_range()` had its own default `max_days=60` parameter which was passed to `generate_date_sequence()`. Even after `date_parser.py` was updated, `FastFlightsProvider.search_flights_range()` forced `max_days=60` whenever `run_explore_query()` called it without specifying `max_days`.
- **Fix**: Update default `max_days: Optional[int] = 330` in `FastFlightsProvider.search_flights_range()`.

### Bug 2: Cancel button didn't stop background HTTP requests
- **Location**: `bot/handlers/common.py` (`cancel_callback`), `services/explore_engine.py` (`run_explore_query`), `providers/fast_flights.py`.
- **Root Cause**: Cancelling the outer `asyncio.Task` did not stop the pending child coroutines in `asyncio.gather` or executor threads. Without a user cancellation check inside the `run_explore_query` loop, background HTTP requests continued executing.
- **Fix**:
  1. In `cancel_callback` in `common.py`, set `set_user_cancelled(user_id)`.
  2. At the start of explore execution, call `clear_user_cancelled(user_id)`.
  3. Pass `user_id` to `run_explore_query`. Before launching airport queries and in `status_cb`, check `is_user_cancelled(user_id)` and abort immediately if true.

## Verification Plan
- Unit test `FastFlightsProvider.search_flights_range` with a 90-day range returns 90 dates.
- Unit test `run_explore_query` with `set_user_cancelled(user_id)` aborts execution instantly.
- Run full pytest test suite to ensure 100% pass rate.
