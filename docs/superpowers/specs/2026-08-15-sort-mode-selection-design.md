# Custom Sort Mode & Dual List Presentation Design Specification

## Overview
This specification details adding custom sort mode selection (`Cheapest Price`, `Highest Discount %`, `Show Both Lists`) and enriched typical price baseline formatting to both the `/explore` and `/search` flight deal query engines and interactive wizards.

---

## 1. User Interface & Wizard Step Design

### Sort Preference Wizard Step
Both `/explore` and `/search` interactive Telegram wizards will include a dedicated sorting step offering 3 inline keyboard choices:
- `💶 Cheapest Price` (`price`): Sorts deals/offers strictly by ticket price ascending (`€`).
- `💥 Highest Discount %` (`discount`): Sorts deals/offers by discount drop percentage descending relative to Google Flights typical average prices. Secondary tie-breaker by price ascending.
- `🔀 Show Both Lists` (`both`): Generates both ranked categories (`Top Discounts` + `Cheapest Flights`) in a single structured response message.

### Button Callback Patterns
- `/explore` wizard: `expl_sort_price`, `expl_sort_discount`, `expl_sort_both`
- `/search` wizard: `src_sort_price`, `src_sort_discount`, `src_sort_both`

---

## 2. Offer Display Formatting

When baseline pricing (`typical_min`, `typical_max`) is available from Google Flights:
- **Discount Percentage**: `((baseline_avg - price) / baseline_avg) * 100`
- **Baseline Average**: `(typical_min + typical_max) / 2.0`

### Display Format
```text
1. SKG ✈️ CDG (Paris Charles de Gaulle)
💶 €99.00 (💥 25% OFF! | Avg: ~€132.00) | 📅 2026-09-14 (Air Serbia)
```

If no typical price metadata is returned by the provider:
```text
1. SKG ✈️ ZAG (Zagreb Franjo Tudman)
💶 €44.00 | 📅 2026-09-14 (Ryanair)
```

---

## 3. Dual List Message Rendering (`sort_by="both"`)

When `sort_by == "both"`:
```text
🌟 Top Flight Deals for SKG → EUROPE

💥 TOP DISCOUNTED DEALS (% OFF)
1. SKG ✈️ CDG (Paris) — €99.00 (💥 35% OFF! | Avg: ~€152.00) | 📅 2026-09-14 (Air Serbia)
2. SKG ✈️ FCO (Rome) — €97.00 (💥 28% OFF! | Avg: ~€135.00) | 📅 2026-09-14 (ITA Airways)

💶 CHEAPEST OVERALL FLIGHTS (€)
1. SKG ✈️ ZAG (Zagreb) — €44.00 | 📅 2026-09-14 (Ryanair)
2. SKG ✈️ SJJ (Sarajevo) — €46.00 | 📅 2026-09-14 (Ryanair)
3. SKG ✈️ OTP (Bucharest) — €64.00 | 📅 2026-09-14 (Ryanair)
```

---

## 4. Query Engine Changes

1. **`services/explore_engine.py`**:
   - `run_explore_query(origin, region, departure_date, max_budget=None, sort_by="discount"|"price"|"both", max_results=10)`
   - Computes baseline average price and discount score.
   - If `sort_by == "both"`, returns dictionary/tuple containing `discount_deals` and `cheapest_deals`.
2. **`bot/handlers/explore.py`**:
   - Updates `_render_explore_deals` to format single or dual sections with 1-tap track deal buttons.
3. **`bot/handlers/search.py`**:
   - Extracts typical min/max baseline prices from provider flight offers.
   - Updates `execute_search` and wizard to render single or dual sections.

---

## 5. Testing & Verification
- Unit tests for `run_explore_query` with `sort_by="both"`, `sort_by="price"`, `sort_by="discount"`.
- Unit tests for `/search` and `/explore` wizard callback handlers and rendering logic.
- Ensure 100% pass rate on test suite.
