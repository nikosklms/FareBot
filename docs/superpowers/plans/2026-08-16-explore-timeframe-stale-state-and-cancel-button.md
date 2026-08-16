# Explore Timeframe Stale State & Cancel Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stale `explore_departure_date` persistence in `/explore` wizard and add an inline "❌ Cancel" button to progress & ETA messages.

**Architecture:** Update `bot/handlers/explore.py` to clear `explore_departure_date` on new wizard start / timeframe button click, and attach cancel keyboard markup to explore progress updates.

**Tech Stack:** Python 3.13, python-telegram-bot, pytest

## Global Constraints
- Preserve existing wizard handler interfaces and state flow.
- Ensure 100% test coverage with pytest.

---

### Task 1: Fix Stale State and Add Cancel Button in `bot/handlers/explore.py`

**Files:**
- Modify: `bot/handlers/explore.py`
- Test: `tests/test_explore_handler.py`

- [ ] **Step 1: Write failing test in `tests/test_explore_handler.py`**

```python
@pytest.mark.asyncio
async def test_explore_timeframe_clears_stale_departure_date():
    context = MagicMock()
    context.user_data = {"explore_departure_date": "2026-08-17..2026-10-16"}
    update = MagicMock()
    update.callback_query.data = "expl_tf_90"
    update.callback_query.answer = AsyncMock()
    
    with patch("bot.handlers.explore._ask_explore_limit") as ask_mock:
        ask_mock.return_value = 5
        await select_explore_timeframe_callback(update, context)
        assert "explore_departure_date" not in context.user_data
        assert context.user_data["explore_timeframe"] == 90
```

- [ ] **Step 2: Run pytest to verify failure**

Run: `./venv/bin/pytest tests/test_explore_handler.py`
Expected: FAIL

- [ ] **Step 3: Modify `bot/handlers/explore.py`**
  - Clear `explore_departure_date` in `start_explore_wizard`, `select_explore_timeframe_callback`, and `handle_explore_timeframe_input`.
  - Add `reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])` to explore start and status_cb messages in `_execute_wizard_explore`.

- [ ] **Step 4: Run pytest to verify all tests pass**

Run: `./venv/bin/pytest`
Expected: PASS (117 passed)

- [ ] **Step 5: Commit changes**

```bash
git add bot/handlers/explore.py tests/test_explore_handler.py
git commit -m "fix: clear stale explore_departure_date on timeframe selection and add cancel button to progress message"
```
