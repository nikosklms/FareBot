# Fix Date Sequence 60-Day Cap & Implement Real Explore Task Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 60-day default cap in `generate_date_sequence` and implement task cancellation when `❌ Cancel` is clicked.

**Architecture:** Update `utils/date_parser.py` (`max_days=330`), update `cancel_callback` in `bot/handlers/common.py` to cancel `active_explore_task`, and catch `asyncio.CancelledError` in `bot/handlers/explore.py`.

**Tech Stack:** Python 3.13, asyncio, python-telegram-bot, pytest

## Global Constraints
- Preserve all existing public contracts.
- Ensure 100% test coverage with pytest.

---

### Task 1: Fix 60-Day Cap in `utils/date_parser.py`

**Files:**
- Modify: `utils/date_parser.py:33`
- Test: `tests/test_date_parser.py`

- [ ] **Step 1: Write test in `tests/test_date_parser.py` for 90-day sequence**

```python
def test_generate_date_sequence_90_days():
    dates = generate_date_sequence("2026-08-17", "2026-11-14")
    assert len(dates) == 90
```

- [ ] **Step 2: Run pytest to verify failure**

Run: `./venv/bin/pytest tests/test_date_parser.py -k "test_generate_date_sequence_90_days"`
Expected: FAIL (returns 60)

- [ ] **Step 3: Update `utils/date_parser.py`**

Change `max_days: Optional[int] = 60` to `max_days: Optional[int] = 330` in `generate_date_sequence`.

- [ ] **Step 4: Run pytest to verify test passes**

Run: `./venv/bin/pytest tests/test_date_parser.py`
Expected: PASS

---

### Task 2: Implement Real Task Cancellation in `bot/handlers/common.py` and `bot/handlers/explore.py`

**Files:**
- Modify: `bot/handlers/common.py:62-69`
- Modify: `bot/handlers/explore.py:342-385`
- Test: `tests/test_common_handlers.py`

- [ ] **Step 1: Write test for cancel callback cancelling task**

```python
@pytest.mark.asyncio
async def test_cancel_callback_cancels_active_task():
    task_mock = MagicMock()
    context = MagicMock()
    context.user_data = {"active_explore_task": task_mock}
    update = MagicMock()
    update.callback_query.message.edit_text = AsyncMock()
    update.callback_query.answer = AsyncMock()

    await cancel_callback(update, context)
    task_mock.cancel.assert_called_once()
    assert "active_explore_task" not in context.user_data
```

- [ ] **Step 2: Update `bot/handlers/common.py` and `bot/handlers/explore.py`**

Store `context.user_data["active_explore_task"] = asyncio.current_task()` in `_execute_wizard_explore` and `explore_command`.
In `cancel_callback`, cancel `active_explore_task` if present. Handle `asyncio.CancelledError` in explore functions.

- [ ] **Step 3: Run pytest to verify all tests pass**

Run: `./venv/bin/pytest`
Expected: PASS (118 passed)

- [ ] **Step 4: Commit changes**

```bash
git add utils/date_parser.py bot/handlers/common.py bot/handlers/explore.py tests/test_date_parser.py tests/test_common_handlers.py
git commit -m "fix: remove 60-day cap from date sequence and cancel background task on cancel callback"
```
