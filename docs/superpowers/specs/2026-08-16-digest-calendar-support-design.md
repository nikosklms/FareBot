# Digest Wizard Interactive Calendar Support Design

## Problem
In `/digest` Step 5/8 (selecting target departure timeframe horizon), the user was presented only with quick preset buttons (`14 Days`, `30 Days`, `60 Days`, `90 Days`) or manual text typing. The interactive date picker calendar (`📆 Custom Date / Range`) present in `/explore` and `/search` was missing.

## Goal
Add the `📆 Custom Date / Range` interactive calendar picker button to Step 5/8 of the `/digest` wizard, allowing users to pick custom departure dates or ranges visually on an interactive inline calendar.

## Proposed Changes

### 1. `bot/handlers/digest.py`
- Update `_ask_digest_timeframe` keyboard to include `[InlineKeyboardButton("📆 Custom Date / Range", callback_data="open_cal_digest")]`.
- Add calendar callback handlers:
  - `open_calendar_digest_callback`
  - `digest_calendar_nav_callback`
  - `digest_calendar_mode_callback`
  - `digest_calendar_ignore_callback`
  - `handle_digest_calendar_date_selection`: converts selected target date/range into days-ahead horizon and moves to Step 6/8 (`DIGEST_DAY`).

### 2. `main.py`
- Import calendar callbacks for digest and register them under `DIGEST_TIMEFRAME` state in `digest_wizard` ConversationHandler.

## Verification Plan
- Write unit tests for `open_calendar_digest_callback` and `handle_digest_calendar_date_selection`.
- Run full pytest test suite to ensure 100% pass rate.
