# Explore Timeframe Stale State & Cancel Button Design

## Problem Statement
1. **Stale Timeframe/Departure Date Bug**: When a user runs an `/explore` search with a custom date range (e.g., 60 days via calendar or previous selection), `context.user_data["explore_departure_date"]` persists across steps and subsequent wizard runs. When the user later selects a preset timeframe (e.g. 90 Days), `_execute_wizard_explore` prefers `explore_departure_date` if present, executing a stale 60-day query instead of the newly selected 90-day range.
2. **Missing Cancel Button**: When `/explore` displays the initial status message and live ETA estimate, there is no inline "❌ Cancel" button on the message, leaving the user unable to cancel long-running queries from Telegram.

## Proposed Changes

### 1. Clear Stale State (`bot/handlers/explore.py`)
- At the start of `start_explore_wizard`, clear `explore_departure_date` and `explore_timeframe` from `context.user_data`.
- In `select_explore_timeframe_callback` and `handle_explore_timeframe_input`, call `context.user_data.pop("explore_departure_date", None)` when a timeframe preset or numeric input is chosen so that `build_timeframe_date_range(tf)` is used.

### 2. Add Inline Cancel Button (`bot/handlers/explore.py`)
- In `_execute_wizard_explore`, attach `reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])` to the initial message and in `status_cb` during live ETA updates.

## Verification Plan
- Test selecting a custom date followed by selecting 90 Days in `/explore` wizard to ensure `explore_departure_date` is properly cleared and 90 days is queried.
- Test `/explore` progress and estimate updates display the "❌ Cancel" inline button.
- Run full pytest test suite to ensure 100% pass rate.
