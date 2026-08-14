# Inline Calendar & Explore Feature Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and integrate the Inline Calendar Date Picker, `/explore` deal discovery engine, 1-tap tracking with `-10%` target price rule, scheduled `/digest` command, deduplication guard, `/dashboard` budget editor, and daily cleanup daemon into FareBot.

**Architecture:** A modular `explore_engine` handles live parallel flight queries across primary country hubs, calculates Google baseline discount percentages, and formats deal cards. `bot/inline_calendar.py` provides an interactive 7-column Telegram keyboard. `database/db.py` handles deduplication guards and budget edits. `daemon/scheduler.py` manages weekly digest runs and midnight cleanup jobs.

**Tech Stack:** Python 3.13, `python-telegram-bot`, `aiosqlite`, `fast_flights`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Must maintain 100% test suite pass rate (`venv/bin/pytest`).
- Follow established FareBot code style, async patterns with `aiosqlite`, and PTB `ContextTypes.DEFAULT_TYPE`.
- File links in documentation must use absolute Markdown links (`file:///...`).

---

### Task 1: Primary Airport Registry (`services/airports_data.py`)

**Files:**
- Modify: `services/airports_data.py`
- Test: `tests/test_airports_data.py`

**Interfaces:**
- Consumes: None
- Produces: `GLOBAL_REGIONS_AIRPORTS: dict[str, list[dict[str, str]]]` containing primary main gateway airports per country across 8 global regions (`europe`, `islands`, `middle_east`, `asia`, `africa`, `oceania`, `latin_america`, `north_america`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_airports_data.py
from services.airports_data import GLOBAL_REGIONS_AIRPORTS, get_region_airports

def test_global_regions_airports_structure():
    assert "europe" in GLOBAL_REGIONS_AIRPORTS
    assert "islands" in GLOBAL_REGIONS_AIRPORTS
    europe_airports = get_region_airports("europe")
    assert len(europe_airports) >= 25
    codes = [a["code"] for a in europe_airports]
    assert "CDG" in codes
    assert "FCO" in codes
    assert "MAD" in codes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_airports_data.py -v`
Expected: FAIL (`ImportError` or `AssertionError`).

- [ ] **Step 3: Write minimal implementation**

Add `GLOBAL_REGIONS_AIRPORTS` dict and `get_region_airports(region_name: str)` in `services/airports_data.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_airports_data.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/airports_data.py tests/test_airports_data.py
git commit -m "feat: add global regions primary airport registry"
```

---

### Task 2: Database Schema & Method Upgrades (`database/db.py`)

**Files:**
- Modify: `database/db.py`
- Test: `tests/test_db_upgrades.py`

**Interfaces:**
- Consumes: SQLite schema in `farebot.db`.
- Produces: `update_budget(tracker_id: int, new_budget: float)`, `has_active_tracker(user_id, origin, destination, departure_date) -> bool`, `has_active_digest(user_id, origin, region, departure_date) -> bool`, `purge_stale_trackers() -> dict[str, int]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_upgrades.py
import pytest
from database.db import DatabaseManager

@pytest.mark.asyncio
async def test_db_upgrades_budget_dedup_and_cleanup(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = DatabaseManager(db_file)
    await db.init_db()

    # Create tracker
    t_id = await db.create_tracker(
        user_id=100, origin_code="ATH", origin_name="Athens",
        destination_code="MJT", destination_name="Mytilene",
        departure_date="2026-09-15", max_budget=90.0
    )
    
    # Test update_budget
    await db.update_budget(t_id, 32.40)
    tracker = await db.get_tracker_by_id(t_id)
    assert tracker["max_budget"] == 32.40

    # Test deduplication check
    assert await db.has_active_tracker(100, "ATH", "MJT", "2026-09-15") is True
    assert await db.has_active_tracker(100, "ATH", "SKG", "2026-09-15") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_db_upgrades.py -v`
Expected: FAIL (`AttributeError: 'DatabaseManager' object has no attribute 'update_budget'`).

- [ ] **Step 3: Write minimal implementation**

Implement `update_budget`, `has_active_tracker`, `has_active_digest`, and `purge_stale_trackers` in `DatabaseManager` in `database/db.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_db_upgrades.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database/db.py tests/test_db_upgrades.py
git commit -m "feat: add update_budget, deduplication guard, and cleanup methods to db.py"
```

---

### Task 3: Telegram Inline Calendar Widget (`bot/inline_calendar.py`)

**Files:**
- Create: `bot/inline_calendar.py`
- Test: `tests/test_inline_calendar.py`

**Interfaces:**
- Consumes: `year: int`, `month: int`.
- Produces: `create_calendar(year: int, month: int) -> InlineKeyboardMarkup` and `parse_calendar_callback(callback_data: str) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inline_calendar.py
from bot.inline_calendar import create_calendar, parse_calendar_callback

def test_calendar_creation_and_callback():
    markup = create_calendar(2026, 9)
    assert markup is not None
    action, data = parse_calendar_callback("cal_day_2026-09-15")
    assert action == "DAY"
    assert data == "2026-09-15"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_inline_calendar.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'bot.inline_calendar'`).

- [ ] **Step 3: Write minimal implementation**

Create `bot/inline_calendar.py` providing interactive 7-column date grid keyboard and callback parser.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_inline_calendar.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/inline_calendar.py tests/test_inline_calendar.py
git commit -m "feat: add interactive Telegram inline calendar widget"
```

---

### Task 4: Explore Engine & Opportunity Scorer (`services/explore_engine.py`)

**Files:**
- Create: `services/explore_engine.py`
- Test: `tests/test_explore_engine.py`

**Interfaces:**
- Consumes: `FastFlightsProvider`, `GLOBAL_REGIONS_AIRPORTS`.
- Produces: `async def run_explore_query(origin: str, region: str, departure_date: str, max_budget: Optional[float] = None, sort_by: str = "discount") -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_explore_engine.py
import pytest
from unittest.mock import AsyncMock, patch
from services.explore_engine import run_explore_query

@pytest.mark.asyncio
async def test_run_explore_query():
    with patch("services.explore_engine.FastFlightsProvider") as provider_cls:
        provider = AsyncMock()
        provider.search_flights.return_value = [
            AsyncMock(price=50.0, airline="Air France")
        ]
        provider_cls.return_value = provider

        deals = await run_explore_query("ATH", "europe", "2026-09-15", max_budget=100.0)
        assert isinstance(deals, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_explore_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.explore_engine'`).

- [ ] **Step 3: Write minimal implementation**

Create `services/explore_engine.py` with parallel querying via `asyncio.gather`, Google Flights baseline discount scoring, and regional diversity cap.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_explore_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/explore_engine.py tests/test_explore_engine.py
git commit -m "feat: add explore engine with baseline discount scoring and diversity capping"
```

---

### Task 5: `/explore` Command Handler & 1-Tap Track (`bot/handlers/explore.py`)

**Files:**
- Create: `bot/handlers/explore.py`
- Modify: `bot/handlers/__init__.py`, `main.py`
- Test: `tests/test_explore_handler.py`

**Interfaces:**
- Consumes: `run_explore_query`, `DatabaseManager`, `bot/inline_calendar.py`.
- Produces: `explore_command(update, context)` and `track_deal_callback(update, context)` implementing 1-tap tracking with `-10%` target price rule (`max_budget = Deal Price - 10%`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_explore_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.explore import explore_command, track_deal_callback

@pytest.mark.asyncio
async def test_track_deal_callback():
    update = MagicMock()
    update.callback_query.data = "track_deal_ATH_MJT_2026-09-15_36.0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.explore.db_manager") as db_mock:
        db_mock.has_active_tracker = AsyncMock(return_value=False)
        db_mock.get_active_trackers_count = AsyncMock(return_value=1)
        db_mock.create_tracker = AsyncMock(return_value=12)

        await track_deal_callback(update, context)
        db_mock.create_tracker.assert_called_once()
        # Verify -10% budget rule (36.0 * 0.9 = 32.40)
        assert abs(db_mock.create_tracker.call_args[1]["max_budget"] - 32.40) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_explore_handler.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'bot.handlers.explore'`).

- [ ] **Step 3: Write minimal implementation**

Create `bot/handlers/explore.py`, wire command handler in `main.py` and `bot/handlers/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_explore_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/explore.py bot/handlers/__init__.py main.py tests/test_explore_handler.py
git commit -m "feat: add /explore command handler and 1-tap track callback with -10% target rule"
```

---

### Task 6: Scheduled `/digest` Command Handler (`bot/handlers/digest.py`)

**Files:**
- Create: `bot/handlers/digest.py`
- Modify: `bot/handlers/__init__.py`, `main.py`
- Test: `tests/test_digest_handler.py`

**Interfaces:**
- Consumes: `explore_engine`, `daemon.schedule_digest_job`.
- Produces: `digest_command(update, context)` for configuring scheduled weekly explore runs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_digest_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.digest import digest_command

@pytest.mark.asyncio
async def test_digest_command():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["ATH", "europe", "80"]

    with patch("bot.handlers.digest.db_manager") as db_mock:
        db_mock.has_active_digest = AsyncMock(return_value=False)
        await digest_command(update, context)
        update.message.reply_text.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_digest_handler.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'bot.handlers.digest'`).

- [ ] **Step 3: Write minimal implementation**

Create `bot/handlers/digest.py` and register `/digest` command in `main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_digest_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/digest.py bot/handlers/__init__.py main.py tests/test_digest_handler.py
git commit -m "feat: add /digest command handler for scheduled weekly explore runs"
```

---

### Task 7: `/dashboard` Budget Editing (`bot/handlers/dashboard.py`)

**Files:**
- Modify: `bot/handlers/dashboard.py`
- Test: `tests/test_dashboard_handler.py`

**Interfaces:**
- Consumes: `db_manager.update_budget`.
- Produces: `✏️ Edit Budget` inline keyboard button on dashboard cards and `dash_editbudget_<id>` callback.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.dashboard import mytracks_command

@pytest.mark.asyncio
async def test_mytracks_shows_edit_button():
    update = MagicMock()
    update.effective_user.id = 123
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    mock_tracker = {
        "id": 1, "status": "ACTIVE", "origin_code": "ATH",
        "destination_code": "MJT", "departure_date": "2026-09-15",
        "max_budget": 50.0, "last_price_found": 36.0, "direct_only": 1
    }

    with patch("bot.handlers.dashboard.db_manager") as db_mock:
        db_mock.get_user_trackers = AsyncMock(return_value=[mock_tracker])
        await mytracks_command(update, context)
        
        reply_markup = update.message.reply_text.call_args[1]["reply_markup"]
        button_labels = [b.text for row in reply_markup.inline_keyboard for b in row]
        assert any("Edit" in label for label in button_labels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_dashboard_handler.py -v`
Expected: FAIL (`AssertionError`).

- [ ] **Step 3: Write minimal implementation**

Add `✏️ Edit Budget` button and `dash_editbudget_<id>` callback handling to `bot/handlers/dashboard.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_dashboard_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/dashboard.py tests/test_dashboard_handler.py
git commit -m "feat: add Edit Budget button and callback to dashboard"
```

---

### Task 8: Integration of Inline Calendar into `/track` and `/search`

**Files:**
- Modify: `bot/handlers/track.py`, `bot/handlers/search.py`
- Test: `tests/test_track_handler.py`, `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `bot/inline_calendar.py`, `db_manager.has_active_tracker`.
- Produces: Inline Calendar date selection in `/track` and `/search` wizards with deduplication checks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_track_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_origin_input

@pytest.mark.asyncio
async def test_handle_origin_input_shows_calendar():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"track_origin": "ATH"}

    with patch("bot.handlers.track.db_manager") as db_mock:
        db_mock.get_active_trackers_count = AsyncMock(return_value=0)
        await handle_origin_input(update, context)
        update.message.reply_text.assert_called_once()
        reply_markup = update.message.reply_text.call_args[1].get("reply_markup")
        assert reply_markup is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_track_handler.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Update `bot/handlers/track.py` and `bot/handlers/search.py` to use `create_calendar()` for date prompts.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_track_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/track.py bot/handlers/search.py tests/test_track_handler.py tests/test_search_handler.py
git commit -m "feat: integrate inline calendar date picker into track and search wizards"
```

---

### Task 9: Daily Midnight Cleanup Daemon Worker (`daemon/scheduler.py`)

**Files:**
- Modify: `daemon/scheduler.py`
- Test: `tests/test_cleanup_daemon.py`

**Interfaces:**
- Consumes: `db_manager.purge_stale_trackers`.
- Produces: `run_daily_cleanup_job(context)` scheduled to execute every midnight UTC.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup_daemon.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_cleanup_daemon.py -v`
Expected: FAIL (`ImportError: cannot import name 'run_daily_cleanup_job'`).

- [ ] **Step 3: Write minimal implementation**

Implement `run_daily_cleanup_job` and register daily midnight job in `daemon/scheduler.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_cleanup_daemon.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/scheduler.py tests/test_cleanup_daemon.py
git commit -m "feat: add daily midnight cleanup daemon for stale and expired trackers"
```

---

### Task 10: Full Integration & Regression Verification

**Files:**
- Test: All test suites in `tests/`

- [ ] **Step 1: Run full test suite**

Run: `venv/bin/pytest`
Expected: All tests pass (`89+ passed`).

- [ ] **Step 2: Final Commit**

```bash
git add .
git commit -m "chore: complete inline calendar, explore, and digest feature upgrades integration"
```
