# Dynamic Measured Latency for Live Status ETA Design

## Problem
Currently, the live ETA completion time estimated for `/explore`, `/digest`, and `/search` uses a static hardcoded multiplier per batch (e.g. 1.25s or 1.85s). Because Google Flights response payload sizes and network latency vary by region, route, and total date count, static estimates can be off by several minutes.

## Goal
Eliminate all static ETA multipliers. Dynamically measure real execution speed per query/batch as requests complete, and update the live status message ETA based on empirical measured throughput.

## Proposed Changes

### 1. `providers/fast_flights.py` / `services/explore_engine.py`
- Introduce a progress callback `progress_callback(completed_count, total_count, elapsed_seconds)` during execution of `search_flights_range` and `run_explore_query`.
- As HTTP requests finish, compute:
  $$\text{measured\_rate} = \frac{\text{elapsed\_seconds}}{\text{completed\_count}}$$
  $$\text{remaining\_seconds} = (\text{total\_queries} - \text{completed\_count}) \times \frac{\text{measured\_rate}}{\text{concurrency\_limit}}$$
- Periodically invoke `status_callback` with the dynamically calculated `remaining_seconds`.

### 2. Live Status Updates
- Live status text updates now reflect real-time actual measured speed, providing pinpoint accuracy for 1,000+ query operations.

## Verification Plan
- Unit test dynamic ETA calculation under varying query counts and latencies.
- Execute test suite (`pytest`) to ensure 100% test pass rate.
