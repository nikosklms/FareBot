# Top 5 Flight Results & Direct vs. Stops Flight Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update Fare Bot's instant search (`/search`) and background daemon trackers (`/newtrack`) to return top 5 flight results (sorted by price ascending) and allow filtering flights by direct/non-stop vs. any stops.

**Architecture:** Extend `FlightOffer` dataclass with `is_direct: bool`, parse leg counts in `parse_google_flights_payload_generic`, add `direct_only INTEGER DEFAULT 0` to SQLite schema with automatic migration, update Telegram search and track conversation wizards, and format up to 5 flight options in search and push notification messages.

**Tech Stack:** Python 3.11+, `python-telegram-bot`, `aiosqlite`, `fast-flights`, `selectolax`, `pytest`, `pytest-asyncio`.

## Global Constraints

- All database operations must remain asynchronous (`aiosqlite`).
- Minimum polling interval remains 6 hours.
- Maximum active trackers per user remains 5.
- Test runner command: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest`.

---

### Task 1: Update FlightOffer Model & FastFlights Direct Flight Parsing

**Files:**
- Modify: `providers/base.py:6-30`
- Modify: `providers/fast_flights.py:33-180`
- Modify: `tests/test_fast_flights.py`

**Interfaces:**
- Consumes: Google Flights HTML payload in `parse_google_flights_payload_generic`
- Produces: `FlightOffer(..., is_direct: bool = True)`, `search_flights(..., direct_only: bool = False)`

- [ ] **Step 1: Write failing test for is_direct parsing and direct_only filtering**

Add to `tests/test_fast_flights.py`:
```python
@pytest.mark.asyncio
async def test_fast_flights_direct_only_filter():
    from providers.fast_flights import FastFlightsProvider
    from providers.base import FlightOffer

    provider = FastFlightsProvider()

    offer_direct = FlightOffer("ATH", "LON", "2026-08-15", price=150.0, is_direct=True)
    offer_stop = FlightOffer("ATH", "LON", "2026-08-15", price=120.0, is_direct=False)

    with patch.object(provider, "search_flights", wraps=provider.search_flights) as mock_search:
        with patch("providers.fast_flights.UrllibFetchIntegration.fetch_html", return_value="<html></html>"):
            with patch("providers.fast_flights.parse_google_flights_payload_generic", return_value=[offer_stop, offer_direct]):
                results_all = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=False)
                assert len(results_all) == 2

                results_direct = await provider.search_flights("ATH", "LON", "2026-08-15", direct_only=True)
                assert len(results_direct) == 1
                assert results_direct[0].is_direct is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_fast_flights.py -v`  
Expected: FAIL with `TypeError: FlightOffer.__init__() got an unexpected keyword argument 'is_direct'` or `unexpected keyword argument 'direct_only'`

- [ ] **Step 3: Update `FlightOffer` and `FastFlightsProvider`**

In `providers/base.py`:
```python
@dataclass
class FlightOffer:
    origin: str
    destination: str
    departure_date: str
    price: float
    currency: str = "EUR"
    return_date: Optional[str] = None
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    booking_url: Optional[str] = None
    is_direct: bool = True
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class AbstractFlightProvider(ABC):
    @abstractmethod
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR",
        direct_only: bool = False
    ) -> List[FlightOffer]:
        pass
```

In `providers/fast_flights.py`:
```python
            legs = flight_info[2]
            is_direct_flight = len(legs) == 1 if isinstance(legs, list) else True
            ...
            offers.append(
                FlightOffer(
                    origin=orig,
                    destination=dest,
                    departure_date=departure_date,
                    return_date=return_date,
                    price=price_val,
                    currency=currency,
                    airline=airline_name,
                    is_direct=is_direct_flight,
                    booking_url=...
                )
            )
```

And in `FastFlightsProvider.search_flights`:
```python
        if direct_only:
            all_offers = [o for o in all_offers if o.is_direct]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_fast_flights.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add providers/base.py providers/fast_flights.py tests/test_fast_flights.py
git commit -m "feat: add is_direct property and direct_only filtering to flight providers"
```

---

### Task 2: Database Schema Update & CRUD Support for `direct_only`

**Files:**
- Modify: `database/db.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: SQLite `trackers` table
- Produces: `direct_only` column migration and updated `create_tracker(..., direct_only: int = 0)`

- [ ] **Step 1: Write failing test for direct_only column in DatabaseManager**

Add to `tests/test_database.py`:
```python
@pytest.mark.asyncio
async def test_db_direct_only_tracker_field():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        t_id = await db.create_tracker(
            user_id=200, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-08-15", max_budget=200.0, direct_only=1
        )

        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["direct_only"] == 1
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_database.py -v`  
Expected: FAIL with `KeyError: 'direct_only'` or `sqlite3.OperationalError`

- [ ] **Step 3: Update `database/db.py` schema & CRUD methods**

Update `init_db()` and `create_tracker`:
```python
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                origin_code TEXT NOT NULL,
                origin_name TEXT NOT NULL,
                destination_code TEXT NOT NULL,
                destination_name TEXT NOT NULL,
                departure_date TEXT NOT NULL,
                return_date TEXT,
                max_budget REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                frequency_hours INTEGER DEFAULT 6,
                direct_only INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                consecutive_failures INTEGER DEFAULT 0,
                last_checked_at TIMESTAMP,
                last_price_found REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN direct_only INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_database.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/db.py tests/test_database.py
git commit -m "feat: add direct_only column and migration to trackers database schema"
```

---

### Task 3: Interactive Tracking Wizard Flight Type Selection (`/newtrack`)

**Files:**
- Modify: `bot/handlers/track.py`
- Modify: `tests/test_track_handler.py`

**Interfaces:**
- Consumes: Telegram ConversationHandler states
- Produces: `FLIGHT_TYPE` state handling direct flights vs. any flights choice

- [ ] **Step 1: Write failing test for flight type wizard step**

Add to `tests/test_track_handler.py`:
```python
@pytest.mark.asyncio
async def test_handle_flight_type_selection():
    from bot.handlers.track import select_flight_type_callback, BUDGET

    update = MagicMock()
    query = MagicMock()
    query.data = "fl_type_1"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    state = await select_flight_type_callback(update, context)
    assert state == BUDGET
    assert context.user_data["direct_only"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_track_handler.py -v`  
Expected: FAIL with `ImportError: cannot import name 'select_flight_type_callback'`

- [ ] **Step 3: Implement `FLIGHT_TYPE` step in `bot/handlers/track.py`**

Add `FLIGHT_TYPE` step after `DEPARTURE_DATE`:
```python
async def handle_departure_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ...
    context.user_data["departure_date"] = date_str

    buttons = [
        [InlineKeyboardButton("✈️ Direct Flights Only", callback_data="fl_type_1")],
        [InlineKeyboardButton("🔄 Any (Direct & Layovers)", callback_data="fl_type_0")]
    ]
    await update.message.reply_text(
        "✈️ **Flight Type Preference**: Select your flight preference:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FLIGHT_TYPE

async def select_flight_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    direct_only = int(query.data.split("_")[2])
    context.user_data["direct_only"] = direct_only

    await query.message.edit_text(
        f"✅ Preference set to: **{'Direct Flights Only' if direct_only else 'Any Flights'}**\n\n"
        "💶 **Step 4/5**: What is your maximum budget threshold in EUR? (e.g., `250`)",
        parse_mode="Markdown"
    )
    return BUDGET
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_track_handler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/track.py tests/test_track_handler.py
git commit -m "feat: add direct vs any flight type selection step to /newtrack wizard"
```

---

### Task 4: Instant Search Top 5 Results & Flight Type Toggle (`/search`)

**Files:**
- Modify: `bot/handlers/search.py`
- Modify: `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `FastFlightsProvider.search_flights(...)`
- Produces: Top 5 flight results list in Telegram message + flight type preference handler

- [ ] **Step 1: Write failing test for Top 5 search output**

Add to `tests/test_search_handler.py`:
```python
@pytest.mark.asyncio
async def test_execute_search_top_5_formatting():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    status_msg = AsyncMock()
    update.message.reply_text.return_value = status_msg

    offers = [
        FlightOffer("ATH", "LON", "2026-08-15", price=100.0 + i * 10, airline=f"Airline {i}", is_direct=(i % 2 == 0))
        for i in range(7)
    ]

    with patch("bot.handlers.search.provider.search_flights", return_value=offers):
        await execute_search(update, origin="ATH", destination="LON", date="2026-08-15")
        status_msg.edit_text.assert_called_once()
        text = status_msg.edit_text.call_args[0][0]
        assert "Top 5" in text or "Search Results" in text
        assert "1️⃣" in text and "5️⃣" in text
        assert "6️⃣" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py -v`  
Expected: FAIL with `AssertionError: '1️⃣' in text`

- [ ] **Step 3: Update `execute_search` and search wizard in `bot/handlers/search.py`**

```python
async def execute_search(
    update: Update, origin: str, destination: str, date: str, direct_only: bool = False
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    filter_label = "Direct Only ✈️" if direct_only else "Any Flights 🔄"
    status_msg = await message.reply_text(f"🔍 Searching top flight offers ({filter_label}) from **{origin}** to **{destination}** on **{date}**...", parse_mode="Markdown")

    offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date, direct_only=direct_only)

    if not offers:
        await status_msg.edit_text("❌ No matching flight offers found for the specified route and date.")
        return

    top_offers = offers[:5]
    reply_lines = [
        f"✈️ **Top {len(top_offers)} Flight Results** ({filter_label})\n",
        f"📍 **Route**: {origin} ✈️ {destination} | 📅 **Date**: {date}\n"
    ]

    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    for i, o in enumerate(top_offers):
        stop_badge = "Direct ✈️" if o.is_direct else "1+ Stops 🔄"
        reply_lines.append(f"{emojis[i]} **€{o.price:.2f}** — {o.airline or 'Various'} ({stop_badge})")

    reply_text = "\n".join(reply_lines)
    lowest = top_offers[0]

    keyboard = []
    if lowest.booking_url:
        keyboard.append([InlineKeyboardButton("🔗 View Best Offer on Google Flights", url=lowest.booking_url)])
    keyboard.append([
        InlineKeyboardButton(f"🔔 Track Lowest (€{lowest.price:.2f})", callback_data=f"track_{origin}_{destination}_{date}_{lowest.price}_{1 if direct_only else 0}")
    ])

    await status_msg.edit_text(reply_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/search.py tests/test_search_handler.py
git commit -m "feat: display top 5 flight offers in search results with flight type filter"
```

---

### Task 5: Daemon Scheduler Top 5 Alerts & `direct_only` Polling

**Files:**
- Modify: `daemon/scheduler.py`
- Modify: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `tracker["direct_only"]`
- Produces: Polling with direct flight filter and multi-offer price drop notification

- [ ] **Step 1: Write failing test for direct_only daemon polling**

Add to `tests/test_scheduler.py`:
```python
@pytest.mark.asyncio
async def test_scheduler_polls_with_direct_only_flag():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 50, "user_id": 100, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 200.0, "direct_only": 1,
        "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=180.0, airline="Aegean", is_direct=True)
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=50, bot=bot_mock)

    provider_mock.search_flights.assert_called_once_with(
        origin="ATH", destination="LON", departure_date="2026-08-15", direct_only=True
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_scheduler.py -v`  
Expected: FAIL with `AssertionError: search_flights called with unexpected arguments`

- [ ] **Step 3: Update `daemon/scheduler.py`**

In `poll_tracker`:
```python
        direct_only = bool(tracker.get("direct_only", 0))
        offers = await self.provider.search_flights(
            origin=tracker["origin_code"],
            destination=tracker["destination_code"],
            departure_date=tracker["departure_date"],
            direct_only=direct_only
        )
```

And in alert message, list top matching offers under target budget:
```python
        matching_offers = [o for o in offers if o.price <= tracker["max_budget"]][:5]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_scheduler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/scheduler.py tests/test_scheduler.py
git commit -m "feat: poll daemon with direct_only filter and format top matching options in alert"
```

---

### Task 6: Full Integration Test & Main Wiring Update

**Files:**
- Modify: `main.py`
- Modify: `bot/handlers/dashboard.py`
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Write integration test for top 5 search & direct tracker creation**

Add to `tests/test_integration.py`:
```python
@pytest.mark.asyncio
async def test_full_system_direct_tracker_creation():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        t_id = await db.create_tracker(
            user_id=777, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-09-01", max_budget=180.0, direct_only=1
        )

        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["direct_only"] == 1
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
```

- [ ] **Step 2: Run complete test suite**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest -v`  
Expected: All tests pass cleanly.

- [ ] **Step 3: Update `main.py` and `bot/handlers/dashboard.py`**

In `bot/handlers/dashboard.py`:
Display `flight_type = "✈️ Direct Only" if t.get("direct_only") else "🔄 Any Flights"` in tracker cards.

- [ ] **Step 4: Commit**

```bash
git add main.py bot/handlers/dashboard.py tests/test_integration.py
git commit -m "feat: complete top 5 search and direct flight filter integration"
```
