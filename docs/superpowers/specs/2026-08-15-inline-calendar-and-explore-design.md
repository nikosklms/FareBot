# Design Specification: FareBot Feature Upgrades
**Date**: 2026-08-15  
**Target Project**: FareBot (Telegram Flight Tracking Bot)  
**Status**: Feature Design & Architectural Spec for Review  

---

## 1. Executive Summary & Goals

This specification defines a major feature upgrade for FareBot to enhance flight discovery, tracking flexibility, user experience, and database health.

### Key Features to Implement:
1. **Interactive Inline Calendar Date Picker**: Replaces manual date text prompts in `/track` and `/search` wizards with a Telegram inline keyboard calendar widget.
2. **`/explore` Command (On-Demand Deal Discovery)**: Searches major primary country airports across global regions, scores price opportunities against Google Flights baselines, and displays top deals ranked by **Highest Discount % First**.
3. **One-Tap Deal Tracking (`Track Deal #X`)**: Instant 1-click tracker creation from `/explore` results with an automatic **`-10%` Target Price Rule** (`max_budget = Deal Price - 10%`).
4. **Scheduled `/digest` Command (Weekly Automated Explore)**: A scheduled, non-polling weekly run of the explore engine at a user-configured day/time (default: Sunday at 15:00).
5. **Comprehensive Global Airport Registry**: Primary gateway airports for all 45+ European countries and 7 global regions (excluding distant/tertiary airports).
6. **Deduplication Guard & `/dashboard` Budget Editing**: Rejects duplicate active trackers/digests, adds `update_budget()` to `database/db.py`, and adds an `✏️ Edit Budget` button to `/dashboard` cards.
7. **Stale & Expired Tracker Cleanup Daemon**: Daily background worker purging expired/stale records older than 30 days and paused trackers older than 60 days.

---

## 2. Feature Detailed Specifications

### Feature 1: Interactive Inline Calendar Date Picker
* **Integration**: Used inside `/track` and `/search` conversation handlers.
* **UI**: 7-column Telegram inline keyboard (`Mon`..`Sun`) with month navigation (`« Prev`, `Next »`), `Range Mode`, and `Cancel`.
* **Rules**: Past dates are unselectable/disabled. Tapping a date selects it immediately.

### Feature 2: `/explore` Command (Deal Discovery)
* **Syntax**: `/explore <origin> [region] [budget]` (e.g. `/explore ATH europe`, `/explore SKG islands`).
* **Workflow**:
  1. Prompts for travel date/range using the **Inline Calendar**.
  2. Concurrently queries primary main hub airports in the target region using `FastFlightsProvider`.
  3. Extracts Google Flights baseline price metrics (`typical_price_min`, `typical_price_max`).
  4. Calculates Discount Percentage: $\text{Discount \%} = \frac{\text{Baseline} - \text{Price}}{\text{Baseline}} \times 100\%$.
  5. Ranks results by **Highest Discount % First**.
  6. Enforces **Regional Diversity Cap**: Max 2 destinations per country in the top 10 list.
  7. Adds inline sort toggle buttons: `🔥 Best Deals (% Off)` and `💰 Lowest Price (€)`.

### Feature 3: One-Tap Track & `-10%` Target Price Rule
* Each deal card in `/explore` includes a **"🔔 Track Deal #X"** inline button.
* Tapping the button sets `max_budget = Deal Price - 10%` (e.g., €36 deal → €32.40 budget) so the user is only notified if the price drops further.
* Saves an `ACTIVE` tracker directly into `farebot.db`.
* Updates button text to `✅ Tracked!`.

### Feature 4: Scheduled `/digest` Command (Weekly Automated Explore)
* **Concept**: `/digest` is a scheduled wrapper around the core `explore_engine`.
* **Execution**: Stays **100% idle** Monday through Saturday. Runs ONCE per week at the user's configured schedule (default: Sunday at 15:00).
* **Syntax**: `/digest <origin> <region> [budget] [schedule:Day@HH:MM]`
* **Output**: Formatted weekly digest message containing top regional deals with **"Track Deal #X"** buttons.

### Feature 5: Global Primary Airport Registry
Only primary main international gateway airports per country are included (excluding remote low-cost tertiary airports):
* 🇪🇺 **Europe**: `CDG`, `FCO`, `MAD`, `BCN`, `AMS`, `FRA`, `MUC`, `VIE`, `BUD`, `PRG`, `WAW`, `LIS`, `DUB`, `BRU`, `ZRH`, `CPH`, `ARN`, `OSL`, `HEL`, `LHR`, `OTP`, `SOF`, `BEG`, `TIA`, `ZAG`, `LJU`, `SKP`, `SJJ`, `DBV`, `SPU`, `VCE`, `NCE`, `OPO`, `EDI`, `KEF`, `LCA`, `ATH`, `SKG`.
* 🇬🇷 **Greek Domestic & Islands**: `MJT`, `SKG`, `HER`, `CHQ`, `RHO`, `JMK`, `JTR`, `CFU`, `PAS`, `ZTH`, `KGS`.
* 🕌 **Middle East**: `DXB`, `AUH`, `DOH`, `TLV`, `AMM`, `RUH`.
* 🌏 **Asia**: `HND`, `BKK`, `SIN`, `ICN`, `DPS`, `DEL`, `PVG`.
* 🌍 **Africa**: `CAI`, `RAK`, `JNB`, `NBO`, `CPT`, `TUN`.
* 🦘 **Oceania**: `SYD`, `MEL`, `AKL`, `BNE`, `PER`.
* 💃 **Latin America**: `MEX`, `CUN`, `GRU`, `EZE`, `BOG`, `LIM`.
* 🗽 **North America**: `JFK`, `MIA`, `LAX`, `ORD`, `YYZ`, `YVR`.

### Feature 6: Deduplication Guard & `/dashboard` Budget Editing
* **Duplicate Detection**: Prevents creating duplicate active trackers or digests matching `(user_id, origin, destination/region, departure_date)`.
* **UX Response**: When a duplicate is detected during 1-tap tracking or `/track`, the bot offers:
  * `[ ✏️ Update Existing Budget ]` (calls `db.update_budget()`).
* **Database Enhancement**:
  * Adds `async def update_budget(self, tracker_id: int, new_budget: float)` to `database/db.py`.
  * Adds `✏️ Edit Budget` inline button to `/dashboard` tracker cards.

### Feature 7: Daily Cleanup Daemon
* Background worker running daily at midnight UTC:
  1. Marks active trackers past departure dates as `EXPIRED`.
  2. Deletes expired trackers and `price_history` logs older than **30 days**.
  3. Deletes trackers paused for > **60 consecutive days**.

---

## 3. System Architecture & Performance Controls

```
+-----------------------------------------------------------------------+
|                             TELEGRAM BOT                              |
|   /track (Inline Calendar)  |  /explore (Instant)  |  /digest (Weekly)|
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                            EXPLORE ENGINE                             |
|  1. Fetches Primary Hubs in Parallel (asyncio.gather, ~3s total)      |
|  2. Extracts Google Flights Baseline (typical_price_min / max)        |
|  3. Scores Deal % & Ranks Highest Discount First                      |
|  4. Enforces Max 2/country Diversity Cap & Generates Track Buttons     |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                         DATABASE & INTEGRITY                          |
|  - Deduplication Guard Check                                          |
|  - One-Tap Track (-10% Budget Rule) -> farebot.db                     |
|  - update_budget() & /dashboard Edit Buttons                          |
|  - Daily Midnight Cleanup Daemon Worker                               |
+-----------------------------------------------------------------------+
```

### Performance & Rate Limit Protection:
* Live parallel queries use `asyncio.gather` with a 12-second timeout per route.
* Benchmark: 5–10 concurrent primary hub queries complete in **under 3.0 seconds**.
* Scheduled `/digest` runs once weekly on Sunday (0 polling overhead during the week).
