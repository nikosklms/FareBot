# Date Range Search and Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable searching and price-tracking across date ranges (e.g. 2026-09-01 to 2026-09-15) in `/search` and `/track`, with user-friendly inline preset buttons and flexible date parsing.

**Architecture:** Create a central date parser/range utility (`utils/date_parser.py`), add `departure_date_end` column to SQLite database schema, add batch/range query support in `FastFlightsProvider` using `asyncio.gather`, update `/search` and `/track` handlers to support date ranges & preset buttons, and update `daemon/scheduler.py` to poll and notify on date ranges.

**Tech Stack:** Python 3.10+, `python-telegram-bot`, `aiosqlite`, `pytest`, `pytest-asyncio`, `fast-flights`.

## Global Constraints

- Date ranges are capped at a maximum of 14 days per search/tracker to prevent rate-limiting by Google Flights.
- Backward compatibility must be maintained: single dates (`departure_date_end` is `None` or empty) must continue working seamlessly.
- SQLite table migrations must use `ALTER TABLE` inside `init_db` with `try/except OperationalError` to prevent breaking existing database files.

---

### Task 1: Date Range Utilities & Flexible Parsing

**Files:**
- Create: `utils/__init__.py`
- Create: `utils/date_parser.py`
- Create: `tests/test_date_parser.py`

**Interfaces:**
- Consumes: Standard library `datetime` module.
- Produces: `parse_date_or_range(raw_input: str) -> Tuple[str, Optional[str]]`, `generate_date_sequence(start_date: str, end_date: str, max_days: int = 14) -> List[str]`, `get_preset_range(preset_key: str) -> Tuple[str, str]`.

- [ ] **Step 1: Write failing tests for date parsing and preset generators**

Create `tests/test_date_parser.py`:
```python
import pytest
from datetime import datetime, timedelta, timezone
from utils.date_parser import parse_date_or_range, generate_date_sequence, get_preset_range

def test_parse_single_iso_date():
    start, end = parse_date_or_range("2026-09-01")
    assert start == "2026-09-01"
    assert end is None

def test_parse_range_dots():
    start, end = parse_date_or_range("2026-09-01..2026-09-15")
    assert start == "2026-09-01"
    assert end == "2026-09-15"

def test_parse_range_colon():
    start, end = parse_date_or_range("2026-09-01:2026-09-10")
    assert start == "2026-09-01"
    assert end == "2026-09-10"

def test_parse_range_word_to():
    start, end = parse_date_or_range("2026-09-01 to 2026-09-05")
    assert start == "2026-09-01"
    assert end == "2026-09-05"

def test_generate_date_sequence_normal():
    dates = generate_date_sequence("2026-09-01", "2026-09-03", max_days=14)
    assert dates == ["2026-09-01", "2026-09-02", "2026-09-03"]

def test_generate_date_sequence_capped():
    dates = generate_date_sequence("2026-09-01", "2026-09-30", max_days=5)
    assert len(dates) == 5
    assert dates[0] == "2026-09-01"
    assert dates[-1] == "2026-09-05"

def test_get_preset_range_next_7_days():
    today = datetime.now(timezone.utc).date()
    start_str, end_str = get_preset_range("next_7_days")
    exp_start = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    exp_end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    assert start_str == exp_start
    assert end_str == exp_end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_date_parser.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'utils'"

- [ ] **Step 3: Implement `utils/date_parser.py`**

Create `utils/__init__.py`:
```python
# Package marker for utils
```

Create `utils/date_parser.py`:
```python
import re
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List

ISO_DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"

def parse_date_or_range(raw_input: str) -> Tuple[str, Optional[str]]:
    """
    Parses a string into (start_date, end_date).
    Supports formats:
    - '2026-09-01' -> ('2026-09-01', None)
    - '2026-09-01..2026-09-15' -> ('2026-09-01', '2026-09-15')
    - '2026-09-01:2026-09-15' -> ('2026-09-01', '2026-09-15')
    - '2026-09-01 to 2026-09-15' -> ('2026-09-01', '2026-09-15')
    """
    clean = raw_input.strip()
    separators = ["..", ":", " to ", " - "]
    
    for sep in separators:
        if sep in clean:
            parts = [p.strip() for p in clean.split(sep)]
            if len(parts) == 2:
                start_dt = datetime.strptime(parts[0], "%Y-%m-%d")
                end_dt = datetime.strptime(parts[1], "%Y-%m-%d")
                if end_dt < start_dt:
                    start_dt, end_dt = end_dt, start_dt
                return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")

    # Single date
    dt = datetime.strptime(clean, "%Y-%m-%d")
    return dt.strftime("%Y-%m-%d"), None

def generate_date_sequence(start_date: str, end_date: str, max_days: int = 14) -> List[str]:
    """Generates an inclusive sequence of ISO date strings between start_date and end_date, capped at max_days."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    dates = []
    curr = start_dt
    while curr <= end_dt and len(dates) < max_days:
        dates.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=1)
    return dates

def get_preset_range(preset_key: str) -> Tuple[str, str]:
    """Calculates ISO start and end dates for preset options."""
    today = datetime.now(timezone.utc).date()
    if preset_key == "this_weekend":
        # Find next Saturday (5)
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        sat = today + timedelta(days=days_until_sat)
        sun = sat + timedelta(days=1)
        return sat.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d")
    elif preset_key == "next_7_days":
        start = today + timedelta(days=1)
        end = today + timedelta(days=7)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    elif preset_key == "next_14_days":
        start = today + timedelta(days=1)
        end = today + timedelta(days=14)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    else:
        raise ValueError(f"Unknown preset_key: {preset_key}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_date_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 1**

```bash
git add utils/__init__.py utils/date_parser.py tests/test_date_parser.py
git commit -m "feat: add date range parser and preset generators"
```

---

### Task 2: Database Schema Update & Migration

**Files:**
- Modify: `database/db.py:33-85`
- Modify: `tests/conftest.py`
- Create: `tests/test_db_migration.py`

**Interfaces:**
- Consumes: SQLite schema `trackers` table.
- Produces: `departure_date_end` field in `trackers` table; updated `create_tracker(...)` accepting `departure_date_end: Optional[str] = None`.

- [ ] **Step 1: Write failing test for `departure_date_end` DB support**

Create `tests/test_db_migration.py`:
```python
import pytest
from database.db import DatabaseManager

@pytest.mark.asyncio
async def test_db_create_tracker_with_departure_date_end(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = DatabaseManager(db_file)
    await db.init_db()

    t_id = await db.create_tracker(
        user_id=123,
        origin_code="ATH",
        origin_name="Athens",
        destination_code="LON",
        destination_name="London",
        departure_date="2026-09-01",
        departure_date_end="2026-09-15",
        max_budget=200.0,
        currency="EUR",
        frequency_hours=6,
        direct_only=1
    )

    tracker = await db.get_tracker_by_id(t_id)
    assert tracker["departure_date"] == "2026-09-01"
    assert tracker["departure_date_end"] == "2026-09-15"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_migration.py -v`
Expected: FAIL with "unexpected keyword argument 'departure_date_end'" or table missing column error.

- [ ] **Step 3: Modify `database/db.py` to add column and update methods**

In `database/db.py`:
1. Add `cursor.execute("ALTER TABLE trackers ADD COLUMN departure_date_end TEXT")` wrapped in `try/except sqlite3.OperationalError: pass` in both sync `init_db` and async `DatabaseManager.init_db`.
2. Update `create_tracker`:
```python
    async def create_tracker(
        self,
        user_id: int,
        origin_code: str,
        origin_name: str,
        destination_code: str,
        destination_name: str,
        departure_date: str,
        max_budget: float,
        return_date: Optional[str] = None,
        currency: str = "EUR",
        frequency_hours: int = 6,
        direct_only: int = 0,
        departure_date_end: Optional[str] = None
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO trackers (
                    user_id, origin_code, origin_name, destination_code, destination_name,
                    departure_date, return_date, max_budget, currency, frequency_hours, direct_only, departure_date_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, origin_code, origin_name, destination_code, destination_name,
                departure_date, return_date, max_budget, currency, frequency_hours, direct_only, departure_date_end
            ))
            await db.commit()
            return cursor.lastrowid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 2**

```bash
git add database/db.py tests/test_db_migration.py
git commit -m "feat: add departure_date_end column to database schema"
```

---

### Task 3: Provider Range Query Support

**Files:**
- Modify: `providers/base.py:25-38`
- Modify: `providers/fast_flights.py:180-244`
- Modify: `tests/test_fast_flights_provider.py`

**Interfaces:**
- Consumes: `generate_date_sequence` from `utils.date_parser`.
- Produces: `search_flights_range(...) -> List[FlightOffer]` method on `AbstractFlightProvider` and `FastFlightsProvider`.

- [ ] **Step 1: Write failing test for `search_flights_range`**

In `tests/test_fast_flights_provider.py` add:
```python
@pytest.mark.asyncio
async def test_search_flights_range():
    provider = FastFlightsProvider()
    with patch.object(provider, 'search_flights', new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = lambda origin, destination, departure_date, **kwargs: [
            FlightOffer(origin=origin, destination=destination, departure_date=departure_date, price=100.0 if departure_date == "2026-09-02" else 150.0)
        ]
        offers = await provider.search_flights_range(
            origin="ATH", destination="LON", start_date="2026-09-01", end_date="2026-09-03"
        )
        assert len(offers) == 3
        assert offers[0].departure_date == "2026-09-02"
        assert offers[0].price == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fast_flights_provider.py -k test_search_flights_range -v`
Expected: FAIL with "AttributeError: 'FastFlightsProvider' object has no attribute 'search_flights_range'"

- [ ] **Step 3: Implement `search_flights_range` in `providers/base.py` and `providers/fast_flights.py`**

In `providers/base.py`:
```python
    async def search_flights_range(
        self,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        """Fetch flight offers across a range of departure dates."""
        pass
```

In `providers/fast_flights.py`:
```python
    async def search_flights_range(
        self,
        origin: str,
        destination: str,
        start_date: str,
        end_date: str,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        from utils.date_parser import generate_date_sequence
        dates = generate_date_sequence(start_date, end_date, max_days=14)
        
        tasks = [
            self.search_flights(
                origin=origin,
                destination=destination,
                departure_date=d,
                currency=currency,
                direct_only=direct_only
            )
            for d in dates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_offers: List[FlightOffer] = []
        for res in results:
            if isinstance(res, list):
                all_offers.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Error fetching flight range: {res}")
                
        all_offers.sort(key=lambda x: x.price)
        return all_offers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fast_flights_provider.py -k test_search_flights_range -v`
Expected: PASS

- [ ] **Step 5: Commit Task 3**

```bash
git add providers/base.py providers/fast_flights.py tests/test_fast_flights_provider.py
git commit -m "feat: add search_flights_range to flight provider"
```

---

### Task 4: Upgrade `/search` Command & Callback Handlers

**Files:**
- Modify: `bot/handlers/search.py:20-247`
- Modify: `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `parse_date_or_range` from `utils.date_parser`, `search_flights_range` from provider.
- Produces: Updated `/search` command supporting date ranges (e.g. `/search ATH LON 2026-09-01..2026-09-15`), inline date preset buttons in wizard search mode, and range tracking callback.

- [ ] **Step 1: Write failing test for date range `/search`**

In `tests/test_search_handler.py`:
```python
@pytest.mark.asyncio
async def test_search_command_with_date_range():
    update = AsyncMock()
    context = AsyncMock()
    context.args = ["ATH", "LON", "2026-09-01..2026-09-03"]
    
    with patch("bot.handlers.search.provider.search_flights_range", new_callable=AsyncMock) as mock_range:
        mock_range.return_value = [
            FlightOffer(origin="ATH", destination="LON", departure_date="2026-09-02", price=90.0, is_direct=True)
        ]
        await search_command(update, context)
        mock_range.assert_called_once_with(
            origin="ATH", destination="LON", start_date="2026-09-01", end_date="2026-09-03", direct_only=False
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search_handler.py -k test_search_command_with_date_range -v`
Expected: FAIL because search command currently passes `2026-09-01..2026-09-03` directly as a single date string.

- [ ] **Step 3: Update `bot/handlers/search.py`**

1. Import `parse_date_or_range` from `utils.date_parser`.
2. In `search_command`, parse the 3rd argument using `parse_date_or_range(args[2])`:
   - If `end_date` is returned, call `provider.search_flights_range(...)`.
   - Else call `provider.search_flights(...)`.
3. Display flight date alongside prices in output formatting (e.g. `1️⃣ **€90.00** (2026-09-02) — Aegean`).
4. Update `search_track_callback_handler` to parse callback data format `track_ATH_LON_2026-09-01_90.0_1_2026-09-15` so that `departure_date_end` is saved to DB.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 4**

```bash
git add bot/handlers/search.py tests/test_search_handler.py
git commit -m "feat: add date range search and tracking callbacks to /search"
```

---

### Task 5: Upgrade `/track` Conversation Handler with Date Presets

**Files:**
- Modify: `bot/handlers/track.py:1-250`
- Modify: `tests/test_track_handler.py`

**Interfaces:**
- Consumes: `get_preset_range`, `parse_date_or_range` from `utils.date_parser`.
- Produces: Updated `/track` wizard with inline preset date buttons (`[This Weekend]`, `[Next 7 Days]`, `[Next 14 Days]`, `[Custom Input]`), saving `departure_date_end` to DB.

- [ ] **Step 1: Write failing test for `/track` preset inline buttons and date range entry**

In `tests/test_track_handler.py`:
```python
@pytest.mark.asyncio
async def test_track_date_preset_button_callback():
    update = AsyncMock()
    update.callback_query.data = "datepreset_next_7_days"
    context = AsyncMock()
    context.user_data = {"origin": "ATH", "destination": "LON"}
    
    state = await handle_date_preset_callback(update, context)
    assert context.user_data.get("departure_date_end") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_track_handler.py -k test_track_date_preset_button_callback -v`
Expected: FAIL with `NameError: handle_date_preset_callback is not defined`.

- [ ] **Step 3: Update `bot/handlers/track.py`**

1. In the `DEPARTURE_DATE` prompt step, output inline keyboard buttons:
   ```python
   keyboard = [
       [InlineKeyboardButton("🗓️ Next 7 Days", callback_data="datepreset_next_7_days"),
        InlineKeyboardButton("✈️ Next 14 Days", callback_data="datepreset_next_14_days")],
       [InlineKeyboardButton("📅 This Weekend", callback_data="datepreset_this_weekend")]
   ]
   ```
2. Add `handle_date_preset_callback` to extract dates from `get_preset_range` and store in `context.user_data["departure_date"]` and `context.user_data["departure_date_end"]`.
3. In `handle_departure_date`, parse user text via `parse_date_or_range(text)`, populating `departure_date` and `departure_date_end`.
4. In `finalize_tracker`, pass `departure_date_end` to `db_manager.create_tracker(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_track_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 5**

```bash
git add bot/handlers/track.py tests/test_track_handler.py
git commit -m "feat: add date range presets and range entry to /track conversation"
```

---

### Task 6: Update Daemon Scheduler for Range Polling

**Files:**
- Modify: `daemon/scheduler.py:35-110`
- Modify: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `tracker["departure_date_end"]` from DB and `search_flights_range` from provider.
- Produces: Polling logic in `daemon/scheduler.py` that handles date range expiration and multi-date price searching.

- [ ] **Step 1: Write failing test for daemon range polling**

In `tests/test_scheduler.py`:
```python
@pytest.mark.asyncio
async def test_scheduler_polls_date_range():
    db_mock = AsyncMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 10, "user_id": 100, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-09-01", "departure_date_end": "2026-09-10",
        "max_budget": 150.0, "status": "ACTIVE", "direct_only": 0, "consecutive_failures": 0
    })
    provider_mock = AsyncMock()
    provider_mock.search_flights_range = AsyncMock(return_value=[
        FlightOffer(origin="ATH", destination="LON", departure_date="2026-09-05", price=120.0)
    ])
    bot_mock = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(10, bot_mock)

    provider_mock.search_flights_range.assert_called_once_with(
        origin="ATH", destination="LON", start_date="2026-09-01", end_date="2026-09-10", direct_only=False
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -k test_scheduler_polls_date_range -v`
Expected: FAIL because `poll_tracker` currently only calls `search_flights`.

- [ ] **Step 3: Update `daemon/scheduler.py`**

In `poll_tracker`:
1. Check expiration: `end_date = tracker.get("departure_date_end") or tracker["departure_date"]`. If `end_date < today_str`, mark EXPIRED.
2. If `tracker.get("departure_date_end")`:
   Call `self.provider.search_flights_range(...)`.
   Else:
   Call `self.provider.search_flights(...)`.
3. Format notification text to state the flight date of the offer that triggered the alert.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 6**

```bash
git add daemon/scheduler.py tests/test_scheduler.py
git commit -m "feat: enable date range polling in daemon scheduler"
```
