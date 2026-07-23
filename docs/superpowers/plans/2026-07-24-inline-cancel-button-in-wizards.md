# Inline Cancel Button in Wizards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interactive `❌ Cancel` inline buttons to every step of the `/search` and `/track` / `/newtrack` interactive wizards so users can cancel instantly with a single button tap at any stage.

**Architecture:** Create a central `cancel_callback` handler in `bot/handlers/common.py`, add `InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")` to prompt keyboards in `search.py` and `track.py`, and register `CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")` as a universal handler/fallback in `ConversationHandler`.

**Tech Stack:** Python 3.10+, `python-telegram-bot`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Must maintain backward compatibility for typing `/cancel` via command text.
- Tapping `❌ Cancel` inline button must instantly answer the callback query, edit the message text to `❌ Action cancelled.`, and return `ConversationHandler.END`.
- Existing unit tests for wizard flows must continue to pass.

---

### Task 1: Create `cancel_callback` in `bot/handlers/common.py`

**Files:**
- Modify: `bot/handlers/common.py`
- Modify: `bot/handlers/__init__.py`
- Test: `tests/test_common.py`

**Interfaces:**
- Consumes: `Update`, `ContextTypes.DEFAULT_TYPE` from `telegram.ext`
- Produces: `cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int` returning `ConversationHandler.END`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.ext import ConversationHandler
from bot.handlers.common import cancel_callback

@pytest.mark.asyncio
async def test_cancel_callback_edits_message():
    update = MagicMock()
    query = MagicMock()
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()

    res = await cancel_callback(update, context)

    assert res == ConversationHandler.END
    query.answer.assert_called_once()
    query.message.edit_text.assert_called_once_with("❌ Action cancelled.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_common.py -v`
Expected: FAIL with "ImportError: cannot import name 'cancel_callback'"

- [ ] **Step 3: Write minimal implementation**

In `bot/handlers/common.py`:
```python
@restricted
async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        if query.message and hasattr(query.message, "edit_text"):
            await query.message.edit_text("❌ Action cancelled.")
    return ConversationHandler.END
```
Export `cancel_callback` in `bot/handlers/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_common.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/common.py bot/handlers/__init__.py tests/test_common.py
git commit -m "feat: add cancel_callback for inline cancel buttons"
```

---

### Task 2: Add `❌ Cancel` Inline Keyboard Buttons to `/search` Wizard

**Files:**
- Modify: `bot/handlers/search.py`
- Test: `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `cancel_callback` from `bot/handlers/common`
- Produces: Updated `search_command`, `handle_search_origin`, `handle_search_destination`, `handle_search_date`, and `select_search_flight_type_callback` including inline Cancel buttons.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_search_wizard_shows_cancel_button():
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    await search_command(update, context)

    reply_markup = update.message.reply_text.call_args[1].get("reply_markup")
    assert reply_markup is not None
    cancel_btn = reply_markup.inline_keyboard[-1][0]
    assert cancel_btn.text == "❌ Cancel"
    assert cancel_btn.callback_data == "cancel_wizard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py::test_search_wizard_shows_cancel_button -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `bot/handlers/search.py`:
Attach `InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")]])` to prompt messages in `search_command`, `select_search_origin_callback`, `select_search_destination_callback`, and `handle_search_date`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/search.py tests/test_search_handler.py
git commit -m "feat: add inline cancel button to search wizard prompts"
```

---

### Task 3: Add `❌ Cancel` Inline Keyboard Buttons to `/track` Wizard & Register Handlers in `main.py`

**Files:**
- Modify: `bot/handlers/track.py`
- Modify: `main.py`
- Test: `tests/test_track_handler.py`

**Interfaces:**
- Consumes: `cancel_callback` in `main.py` conversation fallbacks & states
- Produces: Complete wizard cancellation support via inline buttons across `/search` and `/track`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_start_newtrack_shows_cancel_button():
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    context.user_data = {}

    with patch("bot.handlers.track.db_manager") as db_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=0)
        await start_newtrack(update, context)

    reply_markup = update.message.reply_text.call_args[1].get("reply_markup")
    assert reply_markup is not None
    cancel_btn = reply_markup.inline_keyboard[-1][0]
    assert cancel_btn.text == "❌ Cancel"
    assert cancel_btn.callback_data == "cancel_wizard"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_track_handler.py::test_start_newtrack_shows_cancel_button -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

1. In `bot/handlers/track.py`:
Attach `InlineKeyboardButton("❌ Cancel", callback_data="cancel_wizard")` to keyboards in `start_newtrack`, `select_origin_callback`, `select_destination_callback`, `handle_departure_date`, and `handle_budget`.
2. In `main.py`:
Add `CallbackQueryHandler(cancel_callback, pattern="^cancel_wizard$")` to fallbacks for `search_wizard` and `track_wizard`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest -v`
Expected: PASS (All 85+ tests passing)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/track.py main.py tests/test_track_handler.py
git commit -m "feat: add inline cancel button to track wizard and main ConversationHandlers"
```
