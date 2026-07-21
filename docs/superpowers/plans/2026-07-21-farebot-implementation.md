# Fare Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot ("Fare Bot") that monitors flight prices asynchronously using a background daemon (`python-telegram-bot` JobQueue + SQLite), notifying users when prices drop below target budgets.

**Architecture:** A modular `AbstractFlightProvider` handles flight data fetching (defaulting to `fast-flights`). An interactive Telegram wizard (`ConversationHandler`) collects input with fuzzy city/IATA resolution (`rapidfuzz`). Background daemons poll flight prices every 6–24 hours, managing auto-pausing on price match, 3-strike silent retries, and expiration rules.

**Tech Stack:** Python 3.11+, `python-telegram-bot[job-queue]>=20.0`, `fast-flights`, `rapidfuzz`, `aiosqlite`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Python version floor: 3.11+
- All database operations must be asynchronous (`aiosqlite`).
- Minimum polling interval: 6 hours.
- Maximum active trackers per user: 5.
- Failure threshold before auto-pause alert: 3 consecutive failures.
- Departure date expiration: 00:00 UTC on departure date.
- Test runner command: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest`.

---

### Task 1: FastFlights Provider Implementation

**Files:**
- Create: `providers/fast_flights.py`
- Modify: `providers/__init__.py`
- Test: `tests/test_fast_flights.py`

**Interfaces:**
- Consumes: `AbstractFlightProvider`, `FlightOffer` from `providers/base.py`
- Produces: `FastFlightsProvider` class implementing `search_flights(...)`

- [ ] **Step 1: Write the failing test for FastFlightsProvider**

```python
import pytest
from unittest.mock import patch, MagicMock
from providers.fast_flights import FastFlightsProvider
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_fast_flights_search_success():
    provider = FastFlightsProvider()
    mock_result = MagicMock()
    mock_result.flights = [
        MagicMock(price="€180", name="Aegean Airlines", departure="10:00")
    ]

    with patch("providers.fast_flights.get_flights", return_value=mock_result):
        offers = await provider.search_flights(
            origin="ATH",
            destination="LON",
            departure_date="2026-08-15"
        )
        assert len(offers) == 1
        assert isinstance(offers[0], FlightOffer)
        assert offers[0].price == 180.0
        assert offers[0].origin == "ATH"
        assert offers[0].destination == "LON"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_fast_flights.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'providers.fast_flights'`

- [ ] **Step 3: Write implementation for FastFlightsProvider**

Create `providers/fast_flights.py`:
```python
import asyncio
from typing import List, Optional
from fast_flights import get_flights, FlightData, Passengers
from providers.base import AbstractFlightProvider, FlightOffer

class FastFlightsProvider(AbstractFlightProvider):
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        currency: str = "EUR"
    ) -> List[FlightOffer]:
        loop = asyncio.get_running_loop()

        flight_data = [FlightData(date=departure_date, from_airport=origin, to_airport=destination)]
        if return_date:
            flight_data.append(FlightData(date=return_date, from_airport=destination, to_airport=origin))

        def _fetch():
            return get_flights(
                flight_data=flight_data,
                trip="round-trip" if return_date else "one-way",
                passengers=Passengers(adults=1),
                currency=currency
            )

        try:
            res = await loop.run_in_executor(None, _fetch)
        except Exception as e:
            return []

        offers: List[FlightOffer] = []
        if not res or not hasattr(res, "flights") or not res.flights:
            return offers

        for item in res.flights:
            try:
                # Extract numerical price from string e.g. "€180" or "180 €"
                price_str = getattr(item, "price", "0")
                price_clean = float("".join(c for c in str(price_str) if c.isdigit() or c == "."))
                airline_name = getattr(item, "name", "Unknown Airline")

                offers.append(
                    FlightOffer(
                        origin=origin,
                        destination=destination,
                        departure_date=departure_date,
                        return_date=return_date,
                        price=price_clean,
                        currency=currency,
                        airline=airline_name,
                        booking_url=f"https://www.google.com/travel/flights?q=Flights%20to%20{destination}%20from%20{origin}%20on%20{departure_date}"
                    )
                )
            except Exception:
                continue

        return offers
```

Update `providers/__init__.py`:
```python
from .base import AbstractFlightProvider, FlightOffer
from .fast_flights import FastFlightsProvider

__all__ = ["AbstractFlightProvider", "FlightOffer", "FastFlightsProvider"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_fast_flights.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add providers/fast_flights.py providers/__init__.py tests/test_fast_flights.py
git commit -m "feat: implement FastFlightsProvider with tests"
```

---

### Task 2: Database Schema & Complete CRUD Operations

**Files:**
- Modify: `database/db.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: SQLite schema specification from design doc
- Produces: `DatabaseManager` with full async CRUD methods: `update_tracker_status`, `increment_failure_count`, `reset_failure_count`, `log_price`, `get_user_trackers`, `delete_tracker`, `update_budget`, `get_expired_trackers`

- [ ] **Step 1: Write the failing tests for DatabaseManager CRUD**

Add to `tests/test_database.py`:
```python
@pytest.mark.asyncio
async def test_db_tracker_status_and_failures():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        t_id = await db.create_tracker(
            user_id=100, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-08-15", max_budget=300.0
        )

        # Test failure increment
        fails = await db.increment_failure_count(t_id)
        assert fails == 1
        fails = await db.increment_failure_count(t_id)
        assert fails == 2

        # Test reset failure
        await db.reset_failure_count(t_id)
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["consecutive_failures"] == 0

        # Test update status
        await db.update_tracker_status(t_id, "PAUSED")
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["status"] == "PAUSED"

        # Test log price
        await db.log_price(t_id, 280.0, "Aegean")
        tracker = await db.get_tracker_by_id(t_id)
        assert tracker["last_price_found"] == 280.0

        # Test user trackers list
        user_trackers = await db.get_user_trackers(100)
        assert len(user_trackers) == 1

        # Test delete tracker
        await db.delete_tracker(t_id)
        user_trackers = await db.get_user_trackers(100)
        assert len(user_trackers) == 0

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_database.py -v`  
Expected: FAIL with `AttributeError: 'DatabaseManager' object has no attribute 'increment_failure_count'`

- [ ] **Step 3: Write complete CRUD implementations in `database/db.py`**

Modify `database/db.py`:
```python
import sqlite3
import aiosqlite
from typing import List, Dict, Any, Optional
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        """Initialize tables according to design spec."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
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
                    status TEXT DEFAULT 'ACTIVE',
                    consecutive_failures INTEGER DEFAULT 0,
                    last_checked_at TIMESTAMP,
                    last_price_found REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracker_id INTEGER NOT NULL,
                    price REAL NOT NULL,
                    airline TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
                )
            """)
            await db.commit()

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
        frequency_hours: int = 6,
        currency: str = "EUR"
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO trackers (
                    user_id, origin_code, origin_name, destination_code, destination_name,
                    departure_date, return_date, max_budget, frequency_hours, currency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, origin_code, origin_name, destination_code, destination_name,
                departure_date, return_date, max_budget, frequency_hours, currency
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_active_trackers_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM trackers WHERE user_id = ? AND status = 'ACTIVE'",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_active_trackers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trackers WHERE status = 'ACTIVE'") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_tracker_by_id(self, tracker_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trackers WHERE id = ?", (tracker_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_trackers(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trackers WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_tracker_status(self, tracker_id: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET status = ? WHERE id = ?", (status, tracker_id)
            )
            await db.commit()

    async def update_tracker_budget(self, tracker_id: int, new_budget: float):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET max_budget = ?, status = 'ACTIVE' WHERE id = ?",
                (new_budget, tracker_id)
            )
            await db.commit()

    async def increment_failure_count(self, tracker_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET consecutive_failures = consecutive_failures + 1 WHERE id = ?",
                (tracker_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT consecutive_failures FROM trackers WHERE id = ?", (tracker_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def reset_failure_count(self, tracker_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trackers SET consecutive_failures = 0 WHERE id = ?", (tracker_id,)
            )
            await db.commit()

    async def log_price(self, tracker_id: int, price: float, airline: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            now = datetime.utcnow().isoformat()
            await db.execute(
                "UPDATE trackers SET last_price_found = ?, last_checked_at = ? WHERE id = ?",
                (price, now, tracker_id)
            )
            await db.execute(
                "INSERT INTO price_history (tracker_id, price, airline) VALUES (?, ?, ?)",
                (tracker_id, price, airline)
            )
            await db.commit()

    async def delete_tracker(self, tracker_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
            await db.commit()

    async def get_expired_trackers(self, current_date_str: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trackers WHERE status = 'ACTIVE' AND departure_date < ?",
                (current_date_str,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_database.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/db.py tests/test_database.py
git commit -m "feat: complete DatabaseManager CRUD methods and unit tests"
```

---

### Task 3: Telegram Bot Common Command Handlers (`/start`, `/help`, `/cancel`)

**Files:**
- Create: `bot/handlers/common.py`
- Create: `bot/handlers/__init__.py`
- Test: `tests/test_common_handlers.py`

**Interfaces:**
- Consumes: `python-telegram-bot` update & context objects
- Produces: Async handler functions `start_command`, `help_command`, `cancel_command`

- [ ] **Step 1: Write failing test for common command handlers**

Create `tests/test_common_handlers.py`:
```python
pytest_plugins = ('pytest_asyncio',)
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.handlers.common import start_command, help_command, cancel_command

@pytest.mark.asyncio
async def test_start_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await start_command(update, context)
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Fare Bot" in args[0] or "Fare Bot" in kwargs.get("text", "")

@pytest.mark.asyncio
async def test_help_command():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await help_command(update, context)
    update.message.reply_text.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_common_handlers.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers'`

- [ ] **Step 3: Write implementation for common handlers**

Create `bot/handlers/common.py`:
```python
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "✈️ **Welcome to Fare Bot!**\n\n"
        "I monitor flight prices and send you push notifications when prices drop below your target budget.\n\n"
        "**Available Commands:**\n"
        "🔍 `/search` - Instant single flight search\n"
        "🔔 `/newtrack` - Start a background price tracking daemon\n"
        "📋 `/mytracks` - Manage your active tracking daemons\n"
        "❓ `/help` - View this help guide\n\n"
        "Try typing `/search` or `/newtrack` to get started!"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 **Fare Bot User Guide**\n\n"
        "• **Instant Search**: Type `/search` to find current flight options instantly.\n"
        "• **Tracking Daemon**: Type `/newtrack` to set up background price checks (min 6h frequency).\n"
        "• **Notifications**: When a flight drops below your budget, Fare Bot sends an alert and auto-pauses the job.\n"
        "• **Quotas**: You can have up to 5 active background trackers at a time."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("❌ Action cancelled.", parse_mode="Markdown")
    return ConversationHandler.END
```

Create `bot/handlers/__init__.py`:
```python
from .common import start_command, help_command, cancel_command

__all__ = ["start_command", "help_command", "cancel_command"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_common_handlers.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/common.py bot/handlers/__init__.py tests/test_common_handlers.py
git commit -m "feat: implement common commands start, help, cancel"
```

---

### Task 4: Instant Search Feature (`/search`)

**Files:**
- Create: `bot/handlers/search.py`
- Modify: `bot/handlers/__init__.py`
- Test: `tests/test_search_handler.py`

**Interfaces:**
- Consumes: `LocationResolver`, `AbstractFlightProvider`
- Produces: `search_command`, `search_callback_handler`

- [ ] **Step 1: Write failing test for Search handler**

Create `tests/test_search_handler.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.search import execute_search
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_execute_search_formatting():
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    mock_offer = FlightOffer(
        origin="ATH", destination="LON", departure_date="2026-08-15",
        price=190.0, airline="Aegean", booking_url="http://example.com"
    )

    with patch("bot.handlers.search.FastFlightsProvider.search_flights", return_value=[mock_offer]):
        await execute_search(update, origin="ATH", destination="LON", date="2026-08-15")
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "€190" in text or "190" in text
        assert "Aegean" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.search'`

- [ ] **Step 3: Write implementation for Search Handler**

Create `bot/handlers/search.py`:
```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from providers.fast_flights import FastFlightsProvider
from services.resolver import LocationResolver

resolver = LocationResolver()
provider = FastFlightsProvider()

async def execute_search(
    update: Update, origin: str, destination: str, date: str
) -> None:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    status_msg = await message.reply_text(f"🔍 Searching flights from **{origin}** to **{destination}** on **{date}**...", parse_mode="Markdown")

    offers = await provider.search_flights(origin=origin, destination=destination, departure_date=date)

    if not offers:
        await status_msg.edit_text("❌ No flight offers found for the specified route and date.")
        return

    lowest = min(offers, key=lambda x: x.price)

    reply_text = (
        f"✈️ **Flight Search Results**\n\n"
        f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}\n"
        f"📅 **Date**: {lowest.departure_date}\n"
        f"💶 **Lowest Price**: {lowest.currency} {lowest.price:.2f}\n"
        f"🏢 **Airline**: {lowest.airline or 'Various'}\n"
    )

    keyboard = []
    if lowest.booking_url:
        keyboard.append([InlineKeyboardButton("🔗 View on Google Flights", url=lowest.booking_url)])
    keyboard.append([InlineKeyboardButton("🔔 Track Prices for this Flight", callback_data=f"track_{origin}_{destination}_{date}_{lowest.price}")])

    await status_msg.edit_text(reply_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
```

Update `bot/handlers/__init__.py`:
```python
from .common import start_command, help_command, cancel_command
from .search import execute_search

__all__ = ["start_command", "help_command", "cancel_command", "execute_search"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_search_handler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/search.py bot/handlers/__init__.py tests/test_search_handler.py
git commit -m "feat: implement instant flight search command"
```

---

### Task 5: Interactive Tracking Setup Wizard (`/newtrack`)

**Files:**
- Create: `bot/handlers/track.py`
- Modify: `bot/handlers/__init__.py`
- Test: `tests/test_track_handler.py`

**Interfaces:**
- Consumes: `LocationResolver`, `DatabaseManager`
- Produces: `newtrack_conversation_handler` for `ConversationHandler`

- [ ] **Step 1: Write failing test for Track Handler**

Create `tests/test_track_handler.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.track import handle_origin_input, ORIGIN

@pytest.mark.asyncio
async def test_handle_origin_typo_resolution():
    update = MagicMock()
    update.message.text = "athen"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    next_state = await handle_origin_input(update, context)
    assert next_state == ORIGIN
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "ATH" in args[0] or "ATH" in str(kwargs.get("reply_markup", ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_track_handler.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.track'`

- [ ] **Step 3: Write implementation for Track Handler Wizard**

Create `bot/handlers/track.py`:
```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from services.resolver import LocationResolver
from config import DB_PATH, MAX_TRACKERS_PER_USER
from database.db import DatabaseManager

ORIGIN, DESTINATION, DEPARTURE_DATE, BUDGET, FREQUENCY = range(5)
resolver = LocationResolver()
db_manager = DatabaseManager(DB_PATH)

async def start_newtrack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    active_count = await db_manager.get_active_trackers_count(user_id)
    if active_count >= MAX_TRACKERS_PER_USER:
        await update.message.reply_text(
            f"⚠️ You have reached your limit of {MAX_TRACKERS_PER_USER} active trackers.\n"
            "Please delete an existing tracker using `/mytracks` before creating a new one."
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("🛫 **Step 1/5**: Where are you flying from? (e.g., 'Athens', 'ATH')", parse_mode="Markdown")
    return ORIGIN

async def handle_origin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another city or airport name.")
        return ORIGIN

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"sel_org_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_org")])

    await update.message.reply_text("Please confirm your origin airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return ORIGIN

async def select_origin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_org":
        await query.message.edit_text("🛫 Enter origin city or airport code again:")
        return ORIGIN

    _, _, iata, name = query.data.split("_", 3)
    context.user_data["origin_code"] = iata
    context.user_data["origin_name"] = name

    await query.message.edit_text(
        f"✅ Origin set to: **{iata} - {name}**\n\n"
        "🛬 **Step 2/5**: Where are you flying to? (e.g., 'London', 'LON')",
        parse_mode="Markdown"
    )
    return DESTINATION

async def handle_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    matches = resolver.resolve(text)

    if not matches:
        await update.message.reply_text("❌ Location not recognized. Please try typing another destination.")
        return DESTINATION

    buttons = [
        [InlineKeyboardButton(f"{iata} - {name} ({country})", callback_data=f"sel_dst_{iata}_{name}")]
        for iata, name, country, score in matches[:4]
    ]
    buttons.append([InlineKeyboardButton("🔍 Search Again", callback_data="re_dst")])

    await update.message.reply_text("Please confirm your destination airport:", reply_markup=InlineKeyboardMarkup(buttons))
    return DESTINATION

async def select_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "re_dst":
        await query.message.edit_text("🛬 Enter destination city or airport code again:")
        return DESTINATION

    _, _, iata, name = query.data.split("_", 3)
    context.user_data["destination_code"] = iata
    context.user_data["destination_name"] = name

    await query.message.edit_text(
        f"✅ Destination set to: **{iata} - {name}**\n\n"
        "📅 **Step 3/5**: Enter departure date (`YYYY-MM-DD`):",
        parse_mode="Markdown"
    )
    return DEPARTURE_DATE

async def handle_departure_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    context.user_data["departure_date"] = date_str

    await update.message.reply_text(
        "💶 **Step 4/5**: What is your maximum budget threshold in EUR? (e.g., `250`)",
        parse_mode="Markdown"
    )
    return BUDGET

async def handle_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        budget = float(update.message.text.strip())
        context.user_data["max_budget"] = budget
    except ValueError:
        await update.message.reply_text("❌ Invalid budget amount. Please enter a number (e.g. `250`).")
        return BUDGET

    buttons = [
        [InlineKeyboardButton("6 Hours (Min)", callback_data="freq_6")],
        [InlineKeyboardButton("12 Hours", callback_data="freq_12")],
        [InlineKeyboardButton("24 Hours (Daily)", callback_data="freq_24")]
    ]
    await update.message.reply_text(
        "⏰ **Step 5/5**: How often should Fare Bot check prices?",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return FREQUENCY

async def select_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    freq_hours = int(query.data.split("_")[1])

    user_id = query.from_user.id
    ud = context.user_data

    tracker_id = await db_manager.create_tracker(
        user_id=user_id,
        origin_code=ud["origin_code"],
        origin_name=ud["origin_name"],
        destination_code=ud["destination_code"],
        destination_name=ud["destination_name"],
        departure_date=ud["departure_date"],
        max_budget=ud["max_budget"],
        frequency_hours=freq_hours
    )

    summary = (
        "✅ **Tracking Daemon Initialized!**\n\n"
        f"📍 **Route**: {ud['origin_code']} ✈️ {ud['destination_code']}\n"
        f"📅 **Date**: {ud['departure_date']}\n"
        f"🎯 **Target Budget**: €{ud['max_budget']:.2f}\n"
        f"🔄 **Polling Frequency**: Every {freq_hours} hours\n\n"
        "You will receive a push notification as soon as a price drops below your budget!"
    )
    await query.message.edit_text(summary, parse_mode="Markdown")
    return ConversationHandler.END
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_track_handler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/track.py tests/test_track_handler.py
git commit -m "feat: implement interactive tracking setup wizard"
```

---

### Task 6: Tracker Management Dashboard (`/mytracks`)

**Files:**
- Create: `bot/handlers/dashboard.py`
- Modify: `bot/handlers/__init__.py`
- Test: `tests/test_dashboard_handler.py`

**Interfaces:**
- Consumes: `DatabaseManager`
- Produces: `mytracks_command`, `dashboard_callback_handler`

- [ ] **Step 1: Write failing test for Dashboard handler**

Create `tests/test_dashboard_handler.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.handlers.dashboard import mytracks_command

@pytest.mark.asyncio
async def test_mytracks_empty():
    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.dashboard.db_manager.get_user_trackers", return_value=[]):
        await mytracks_command(update, context)
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "no active or saved flight trackers" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_dashboard_handler.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.dashboard'`

- [ ] **Step 3: Write implementation for Dashboard Handler**

Create `bot/handlers/dashboard.py`:
```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH
from database.db import DatabaseManager

db_manager = DatabaseManager(DB_PATH)

async def mytracks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    trackers = await db_manager.get_user_trackers(user_id)

    if not trackers:
        await update.message.reply_text("📋 You have no active or saved flight trackers. Create one using `/newtrack`!", parse_mode="Markdown")
        return

    for t in trackers:
        status_icon = "🟢" if t["status"] == "ACTIVE" else "⏸️" if t["status"] == "PAUSED" else "🔴"
        text = (
            f"{status_icon} **Tracker #{t['id']}**\n"
            f"📍 **Route**: {t['origin_code']} ✈️ {t['destination_code']}\n"
            f"📅 **Date**: {t['departure_date']}\n"
            f"🎯 **Target Budget**: €{t['max_budget']:.2f}\n"
            f"📊 **Status**: {t['status']}\n"
            f"💶 **Last Price**: €{t['last_price_found']:.2f}" if t['last_price_found'] else "💶 **Last Price**: Not checked yet"
        )

        buttons = []
        if t["status"] == "ACTIVE":
            buttons.append(InlineKeyboardButton("⏸ Pause", callback_data=f"dash_pause_{t['id']}"))
        elif t["status"] == "PAUSED":
            buttons.append(InlineKeyboardButton("▶️ Resume", callback_data=f"dash_resume_{t['id']}"))

        buttons.append(InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{t['id']}"))

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([buttons]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_dashboard_handler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/dashboard.py tests/test_dashboard_handler.py
git commit -m "feat: implement tracker management dashboard"
```

---

### Task 7: Daemon Scheduler & Polling Engine

**Files:**
- Create: `daemon/scheduler.py`
- Create: `daemon/__init__.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `DatabaseManager`, `FastFlightsProvider`, `JobQueue`
- Produces: `TrackerDaemonScheduler` class managing jobs, price checks, auto-pausing, 3-strike retries, and expiry rules.

- [ ] **Step 1: Write failing test for Scheduler Logic**

Create `tests/test_scheduler.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from daemon.scheduler import TrackerDaemonScheduler
from providers.base import FlightOffer

@pytest.mark.asyncio
async def test_scheduler_check_price_match():
    db_mock = MagicMock()
    db_mock.get_tracker_by_id = AsyncMock(return_value={
        "id": 1, "user_id": 100, "origin_code": "ATH", "destination_code": "LON",
        "departure_date": "2026-08-15", "max_budget": 200.0, "consecutive_failures": 0, "status": "ACTIVE"
    })
    db_mock.log_price = AsyncMock()
    db_mock.update_tracker_status = AsyncMock()
    db_mock.reset_failure_count = AsyncMock()

    provider_mock = MagicMock()
    provider_mock.search_flights = AsyncMock(return_value=[
        FlightOffer("ATH", "LON", "2026-08-15", price=180.0, airline="Aegean")
    ])

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler = TrackerDaemonScheduler(db_mock, provider_mock)
    await scheduler.poll_tracker(tracker_id=1, bot=bot_mock)

    db_mock.log_price.assert_called_once_with(1, 180.0, "Aegean")
    db_mock.update_tracker_status.assert_called_once_with(1, "PAUSED")
    bot_mock.send_message.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_scheduler.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.scheduler'`

- [ ] **Step 3: Write implementation for Daemon Scheduler**

Create `daemon/scheduler.py`:
```python
import logging
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from database.db import DatabaseManager
from providers.base import AbstractFlightProvider
from config import MAX_CONSECUTIVE_FAILURES

logger = logging.getLogger(__name__)

class TrackerDaemonScheduler:
    def __init__(self, db: DatabaseManager, provider: AbstractFlightProvider):
        self.db = db
        self.provider = provider

    async def poll_tracker(self, tracker_id: int, bot: Bot):
        tracker = await self.db.get_tracker_by_id(tracker_id)
        if not tracker or tracker["status"] != "ACTIVE":
            return

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        if tracker["departure_date"] < today_str:
            await self.db.update_tracker_status(tracker_id, "EXPIRED")
            await bot.send_message(
                chat_id=tracker["user_id"],
                text=f"ℹ️ Your tracker for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** on **{tracker['departure_date']}** has expired as the departure date has passed.",
                parse_mode="Markdown"
            )
            return

        offers = await self.provider.search_flights(
            origin=tracker["origin_code"],
            destination=tracker["destination_code"],
            departure_date=tracker["departure_date"]
        )

        if not offers:
            fails = await self.db.increment_failure_count(tracker_id)
            if fails >= MAX_CONSECUTIVE_FAILURES:
                await self.db.update_tracker_status(tracker_id, "PAUSED")
                await bot.send_message(
                    chat_id=tracker["user_id"],
                    text=f"⚠️ Unable to check prices for **{tracker['origin_code']} ✈️ {tracker['destination_code']}** after 3 attempts. Tracker paused.",
                    parse_mode="Markdown"
                )
            return

        await self.db.reset_failure_count(tracker_id)
        lowest = min(offers, key=lambda x: x.price)
        await self.db.log_price(tracker_id, lowest.price, lowest.airline)

        if lowest.price <= tracker["max_budget"]:
            await self.db.update_tracker_status(tracker_id, "PAUSED")
            alert_text = (
                "🚨 **PRICE DROP ALERT!** 🚨\n\n"
                f"📍 **Route**: {lowest.origin} ✈️ {lowest.destination}\n"
                f"📅 **Date**: {lowest.departure_date}\n"
                f"🎯 **Target Budget**: €{tracker['max_budget']:.2f}\n"
                f"💶 **Current Price**: **€{lowest.price:.2f}**\n"
                f"🏢 **Airline**: {lowest.airline or 'Various'}"
            )
            buttons = [
                [InlineKeyboardButton("🔗 View & Book Flight", url=lowest.booking_url or "https://www.google.com/travel/flights")],
                [InlineKeyboardButton("⏸ Keep Paused", callback_data=f"dash_pause_{tracker_id}"), InlineKeyboardButton("🗑️ Delete", callback_data=f"dash_del_{tracker_id}")]
            ]
            await bot.send_message(
                chat_id=tracker["user_id"],
                text=alert_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
```

Create `daemon/__init__.py`:
```python
from .scheduler import TrackerDaemonScheduler

__all__ = ["TrackerDaemonScheduler"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_scheduler.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/scheduler.py daemon/__init__.py tests/test_scheduler.py
git commit -m "feat: implement daemon scheduler logic with retries and alerts"
```

---

### Task 8: Application Entry Point (`main.py`) & System Integration Verification

**Files:**
- Create: `main.py`
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: All handlers, database manager, daemon scheduler
- Produces: Runnable Telegram Application instance initializing database and starting bot loop.

- [ ] **Step 1: Write integration test verifying full application wiring**

Create `tests/test_integration.py`:
```python
import pytest
import os
import tempfile
from database.db import DatabaseManager
from providers.fast_flights import FastFlightsProvider
from daemon.scheduler import TrackerDaemonScheduler

@pytest.mark.asyncio
async def test_full_system_wiring():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db = DatabaseManager(db_path)
        await db.init_db()

        provider = FastFlightsProvider()
        scheduler = TrackerDaemonScheduler(db, provider)

        # Create tracker & verify
        t_id = await db.create_tracker(
            user_id=555, origin_code="ATH", origin_name="Athens",
            destination_code="LON", destination_name="London",
            departure_date="2026-12-01", max_budget=200.0
        )
        assert t_id > 0

        active = await db.get_active_trackers()
        assert len(active) == 1

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_integration.py -v`  
Expected: PASS

- [ ] **Step 3: Write `main.py` entry point**

Create `main.py`:
```python
import logging
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
from config import TELEGRAM_BOT_TOKEN, DB_PATH
from database.db import DatabaseManager
from providers.fast_flights import FastFlightsProvider
from daemon.scheduler import TrackerDaemonScheduler
from bot.handlers import start_command, help_command, cancel_command, execute_search
from bot.handlers.track import (
    start_newtrack, handle_origin_input, select_origin_callback,
    handle_destination_input, select_destination_callback,
    handle_departure_date, handle_budget, select_frequency_callback,
    ORIGIN, DESTINATION, DEPARTURE_DATE, BUDGET, FREQUENCY
)
from bot.handlers.dashboard import mytracks_command

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable is not set!")
        return

    db = DatabaseManager(DB_PATH)
    await db.init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mytracks", mytracks_command))

    track_wizard = ConversationHandler(
        entry_points=[CommandHandler("newtrack", start_newtrack)],
        states={
            ORIGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_origin_input),
                CallbackQueryHandler(select_origin_callback, pattern="^sel_org_|re_org")
            ],
            DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_destination_input),
                CallbackQueryHandler(select_destination_callback, pattern="^sel_dst_|re_dst")
            ],
            DEPARTURE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_departure_date)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget)],
            FREQUENCY: [CallbackQueryHandler(select_frequency_callback, pattern="^freq_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )
    app.add_handler(track_wizard)

    print("🤖 Fare Bot is starting...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run complete test suite**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest -v`  
Expected: All tests pass cleanly.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_integration.py
git commit -m "feat: complete Fare Bot main entry point and integration tests"
```
