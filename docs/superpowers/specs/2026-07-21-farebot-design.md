# Fare Bot — Technical System Design

**Date**: 2026-07-21  
**Project**: Fare Bot (Flight Price Tracker Daemon Bot)  
**Stack**: Python 3.11+, `python-telegram-bot` (v20+ async), SQLite, `fast-flights` / `rapidfuzz`

---

## 1. Overview & Core Requirements

Fare Bot is a Telegram bot that allows users to monitor flight prices and receive push notifications when prices drop below a specified budget threshold.

### Key Capabilities
- **Instant Search (`/search`)**: One-time live flight price lookup without creating a daemon.
- **Background Daemon (`/newtrack`)**: Indefinite background tracking job checking prices at custom intervals (minimum 6 hours).
- **Interactive Wizard (`ConversationHandler`)**: Step-by-step input setup with fuzzy typo matching for cities and airport codes (e.g. `athen` -> `ATH - Athens Intl`).
- **Dashboard (`/mytracks`)**: Management interface to view, pause, edit budget, or delete active background trackers.
- **$0 Running Cost**: Uses `fast-flights` (Google Flights reverse-engineered scraper) as the default data source, avoiding mandatory paid API keys.

---

## 2. Architecture & Components

```
                    +------------------------------------+
                    |       Telegram User Interface      |
                    | (/search, /newtrack, /mytracks)    |
                    +-----------------+------------------+
                                      |
                                      v
                    +-----------------+------------------+
                    |    Telegram Bot Handler Layer      |
                    | (ConversationHandler & Commands)   |
                    +--------+------------------+--------+
                             |                  |
                             v                  v
       +---------------------+---+          +---+--------------------+
       | Fuzzy Location Resolver |          |  JobQueue Scheduler    |
       |  (rapidfuzz + IATA DB)  |          | (PTB APScheduler)      |
       +-------------------------+          +-----------+------------+
                                                        |
                                                        v
                                            +-----------+------------+
                                            | Abstract FlightProvider|
                                            |        Interface       |
                                            +-----+--------------+---+
                                                  |              |
                                  +---------------+              +---------------+
                                  v                                              v
                      +-----------+------------+                    +------------+-----------+
                      | FastFlightsProvider    |                    | SerpApiProvider        |
                      | (Default: Google Fl.)  |                    | (Fallback / Swap)      |
                      +------------------------+                    +------------------------+
```

### Component Boundaries & Responsibilities

1. **`bot/handlers/`**: Handles Telegram commands, inline keyboard button callbacks, and `ConversationHandler` wizards.
2. **`services/resolver.py`**: Uses `rapidfuzz` against a local dataset of global cities/airports to turn user string inputs (e.g. `"athen"`) into structured IATA tuples `("ATH", "Athens Eleftherios Venizelos")`.
3. **`providers/base.py`**: Abstract base class `AbstractFlightProvider` with `search_flights(origin, destination, date, return_date) -> List[FlightOffer]`.
4. **`providers/fast_flights.py`**: Primary default scraper provider using `fast-flights`.
5. **`providers/serpapi.py` / `providers/duffel.py`**: Alternative provider adapters implementing `AbstractFlightProvider`.
6. **`database/db.py`**: SQLite database manager wrapping async connections, tracker CRUD operations, and price history tracking.
7. **`daemon/scheduler.py`**: Integrates with `python-telegram-bot`'s `JobQueue` to schedule, run, retry, and manage background polling jobs.

---

## 3. Database Schema (SQLite `farebot.db`)

### `trackers` Table
```sql
CREATE TABLE IF NOT EXISTS trackers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    origin_code TEXT NOT NULL,          -- e.g. 'ATH'
    origin_name TEXT NOT NULL,          -- e.g. 'Athens Intl'
    destination_code TEXT NOT NULL,     -- e.g. 'LON'
    destination_name TEXT NOT NULL,     -- e.g. 'London (All Airports)'
    departure_date TEXT NOT NULL,       -- 'YYYY-MM-DD'
    return_date TEXT,                   -- 'YYYY-MM-DD' or NULL
    max_budget REAL NOT NULL,           -- e.g. 250.00
    currency TEXT DEFAULT 'EUR',
    frequency_hours INTEGER DEFAULT 6,  -- Minimum 6
    status TEXT DEFAULT 'ACTIVE',       -- 'ACTIVE', 'PAUSED', 'EXPIRED', 'COMPLETED'
    consecutive_failures INTEGER DEFAULT 0,
    last_checked_at TIMESTAMP,
    last_price_found REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `price_history` Table
```sql
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL,
    price REAL NOT NULL,
    airline TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tracker_id) REFERENCES trackers(id) ON DELETE CASCADE
);
```

---

## 4. User Interaction Workflows

### Instant Search (`/search`)
1. User types `/search` (or `/search ATH LON 2026-08-15`).
2. Bot prompts for missing details using interactive buttons.
3. Bot queries `FlightProvider` immediately once.
4. Bot formats results (lowest price, airline, times, direct link).
5. Bot attaches inline button: `[ 🔔 Track Prices for this Flight ]` to convert into a background daemon.

### Setup Wizard (`/newtrack`)
1. **Origin Prompt**: User types city/code (e.g. `"athen"`). Bot uses fuzzy search to offer matching inline buttons (`ATH - Athens Intl`).
2. **Destination Prompt**: User types destination city/code. Bot presents matching inline buttons.
3. **Departure Date Prompt**: Accepts `YYYY-MM-DD` or quick inline buttons (`[Next Weekend]`, `[In 2 Weeks]`).
4. **Return Date Prompt**: Optional (`[Skip / One Way]`).
5. **Max Budget Prompt**: User enters target amount (e.g. `250`).
6. **Frequency Selection**: Buttons: `[ 6 Hours (Min) ]`, `[ 12 Hours ]`, `[ 24 Hours (Daily) ]`.
7. **Confirmation & Daemon Spawn**: Saves record to SQLite and registers job in `JobQueue`.

### Tracker Management Dashboard (`/mytracks`)
- Displays all active/paused trackers for the user.
- Interactive inline buttons per tracker:
  - `[ ⏸ Pause / ▶️ Resume ]`
  - `[ ✏️ Edit Budget ]`
  - `[ 🔍 Check Price Now ]`
  - `[ 🗑️ Delete ]`

---

## 5. Daemon & Resilience Rules

1. **Persistence & Recovery**: On bot startup, an initialization hook queries SQLite for `status = 'ACTIVE'` trackers and registers them into `context.job_queue.run_repeating(interval=frequency_hours*3600)`.
2. **Budget Match Alert**: When `lowest_found_price <= max_budget`:
   - Sends Telegram push notification with flight info, price drop comparison, and booking link.
   - Sets DB status to `PAUSED`.
   - Includes inline action buttons: `[ 🔄 Lower Budget & Resume ]`, `[ ⏸ Keep Paused ]`, `[ 🗑️ Delete ]`.
3. **Automatic Expiry Rule**: At 00:00 UTC on the flight departure date:
   - Sets DB status to `EXPIRED`.
   - Removes job from `JobQueue`.
   - Sends notification: *"ℹ️ Your tracker for ATH -> LON (15 Aug 2026) has expired as the departure date passed."*
4. **Error & Retry Logic (Option A - Silent Retry)**:
   - If a scrape fails, log error, increment `consecutive_failures`, and wait for next scheduled check (6h later).
   - If `consecutive_failures >= 3` (18 hours of consecutive failures):
     - Auto-pause tracker in DB (`status = 'PAUSED'`).
     - Notify user: *"⚠️ Unable to check prices for ATH -> LON for 18h. Tracker paused."*
5. **User Quotas**: Hard limit of **5 active trackers** per Telegram User ID.

---

## 6. Verification & Test Plan

- **Unit Tests**:
  - `test_resolver.py`: Test fuzzy city parsing (`"athen"` -> `ATH`, `"london"` -> `LON`).
  - `test_providers.py`: Mock `AbstractFlightProvider` responses for price drops below and above budget.
  - `test_database.py`: Test CRUD operations, quota checks, and state transitions (`ACTIVE` -> `PAUSED` -> `EXPIRED`).
- **Integration Tests**:
  - `test_daemon.py`: Test job creation, automatic retry counter incrementing, 3-strikes auto-pause, and expiration date checks.
