"""Measure how fast the bot can query Google Flights, and when Google starts pushing back.

Usage:
    venv/bin/python -m tools.benchmark                      # 60 queries at concurrency 3
    venv/bin/python -m tools.benchmark --concurrency 3 5    # one batch per setting
    venv/bin/python -m tools.benchmark --queries 100 --pause 60

This sends real requests from this machine's IP. Too much concurrency gets CAPTCHAs,
which also block a running bot for a while, so start small. A batch that hits rate
limiting stops the remaining batches.
"""
import argparse
import asyncio
import logging
import resource
import statistics
import time
from dataclasses import dataclass
from datetime import date, timedelta

from providers.fast_flights import FastFlightsProvider
from services.airports_data import get_region_airports

ORIGIN = "ATH"


@dataclass
class BatchResult:
    concurrency: int
    queries: int
    seconds: float
    request_latencies: list[float]
    empty_results: int
    rate_limit_events: int
    cpu_seconds: float

    @property
    def per_minute(self) -> float:
        return self.queries / self.seconds * 60


class RateLimitCounter(logging.Handler):
    """Counts the provider's rate-limit warnings (CAPTCHA pages, HTTP 429/403, retries)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "RATE_LIMIT" in record.getMessage():
            self.count += 1


def routes(count: int, batch: int = 0, first_day_offset: int = 21) -> list[tuple[str, str]]:
    """Single-airport destinations around Europe on distinct dates; each batch gets new dates."""
    airports = [a["code"] for a in get_region_airports("europe") if a["country"] not in ("Greece", "Cyprus")]
    days_per_batch = -(-count // len(airports))
    first_day = date.today() + timedelta(days=first_day_offset + batch * days_per_batch)
    return [(airports[i % len(airports)], (first_day + timedelta(days=i // len(airports))).isoformat())
            for i in range(count)]


async def run_batch(concurrency: int, queries: int, batch: int = 0, first_day: int = 21) -> BatchResult:
    provider = FastFlightsProvider()
    provider.concurrency = concurrency
    counter = RateLimitCounter()
    logging.getLogger("providers.fast_flights").addHandler(counter)

    cpu_start, wall_start = time.process_time(), time.perf_counter()
    results = await asyncio.gather(*(provider.search_flights(ORIGIN, dest, day) for dest, day in routes(queries, batch, first_day)))
    seconds = time.perf_counter() - wall_start

    logging.getLogger("providers.fast_flights").removeHandler(counter)
    return BatchResult(
        concurrency=concurrency,
        queries=queries,
        seconds=seconds,
        request_latencies=provider.latency_samples(),
        empty_results=sum(1 for offers in results if not offers),
        rate_limit_events=counter.count,
        cpu_seconds=time.process_time() - cpu_start,
    )


def report(result: BatchResult) -> str:
    latencies = sorted(result.request_latencies) or [0.0]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    return "\n".join([
        f"Concurrency {result.concurrency}: {result.queries} queries in {result.seconds:.1f}s "
        f"= {result.per_minute:.0f} queries/min",
        f"  per request: median {statistics.median(latencies):.2f}s, p95 {p95:.2f}s, "
        f"min {latencies[0]:.2f}s, max {latencies[-1]:.2f}s",
        f"  no offers: {result.empty_results}/{result.queries}   rate-limit events: {result.rate_limit_events}",
        f"  CPU: {result.cpu_seconds:.1f}s ({result.cpu_seconds / result.seconds * 100:.0f}% of one core)",
        *(["  ⚠️  Most queries returned no offers: Google may be serving a consent or error page, "
           "so these numbers are not valid."] if result.empty_results > result.queries / 2 else []),
    ])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=60, help="queries per batch (default 60)")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[3], help="settings to try (default 3)")
    parser.add_argument("--pause", type=float, default=30, help="seconds between batches (default 30)")
    parser.add_argument("--first-day", type=int, default=21, help="days from today of the first query date")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR, format="%(message)s")

    for index, concurrency in enumerate(args.concurrency):
        if index:
            print(f"\nPausing {args.pause:.0f}s so Google cools down…", flush=True)
            await asyncio.sleep(args.pause)
        result = await run_batch(concurrency, args.queries, batch=index, first_day=args.first_day)
        print(report(result), flush=True)
        if result.rate_limit_events:
            print("\nGoogle started rate limiting; stopping here.")
            break

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"\nPeak memory: {peak_mb:.0f} MB")


if __name__ == "__main__":
    asyncio.run(main())
