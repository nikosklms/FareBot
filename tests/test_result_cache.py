import asyncio

import httpx
import pytest

from providers.base import FlightOffer, FlightSearchError
from providers.fast_flights import FastFlightsProvider
from providers.result_cache import ResultCache
from tests.test_fast_flights import mock_client, results_page


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def offer(price: float) -> FlightOffer:
    return FlightOffer(origin="ATH", destination="LHR", departure_date="2026-11-21", price=price)


class Fetcher:
    """Counts calls; each call waits for `release` (when given) and returns the next result."""

    def __init__(self, *results, release: asyncio.Event = None) -> None:
        self.results = list(results)
        self.calls = 0
        self.release = release
        self.cancelled = False

    async def __call__(self):
        self.calls += 1
        result = self.results.pop(0)
        try:
            if self.release:
                await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if isinstance(result, Exception):
            raise result
        return result


async def test_repeated_search_is_served_from_the_cache():
    cache, fetch = ResultCache(), Fetcher([offer(83)])
    first = await cache.get_or_fetch("k", fetch)
    first.clear()  # callers get their own list
    assert [o.price for o in await cache.get_or_fetch("k", fetch)] == [83]
    assert fetch.calls == 1 and (cache.hits, cache.misses) == (1, 1)


async def test_different_searches_are_cached_separately():
    cache = ResultCache()
    assert (await cache.get_or_fetch("a", Fetcher([offer(1)])))[0].price == 1
    assert (await cache.get_or_fetch("b", Fetcher([offer(2)])))[0].price == 2


async def test_results_expire():
    clock = Clock()
    cache, fetch = ResultCache(ttl=60, clock=clock), Fetcher([offer(83)], [offer(90)])
    await cache.get_or_fetch("k", fetch)
    clock.now += 59
    assert (await cache.get_or_fetch("k", fetch))[0].price == 83
    clock.now += 2
    assert (await cache.get_or_fetch("k", fetch))[0].price == 90
    assert fetch.calls == 2


async def test_oldest_results_are_dropped_past_the_limit():
    cache = ResultCache(max_entries=2)
    for key in ("a", "b", "c"):
        await cache.get_or_fetch(key, Fetcher([offer(1)]))
    assert len(cache) == 2
    fetch = Fetcher([offer(5)])
    await cache.get_or_fetch("a", fetch)
    assert fetch.calls == 1


async def test_identical_searches_running_at_once_share_one_request():
    release = asyncio.Event()
    cache, fetch = ResultCache(), Fetcher([offer(83)], release=release)
    searches = [asyncio.create_task(cache.get_or_fetch("k", fetch)) for _ in range(3)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*searches)
    assert [r[0].price for r in results] == [83, 83, 83]
    assert fetch.calls == 1 and cache.shared == 2


async def test_failures_reach_every_waiter_and_are_not_cached():
    release = asyncio.Event()
    cache = ResultCache()
    fetch = Fetcher(FlightSearchError("blocked"), [offer(83)], release=release)
    searches = [asyncio.create_task(cache.get_or_fetch("k", fetch)) for _ in range(2)]
    await asyncio.sleep(0)
    release.set()
    for result in await asyncio.gather(*searches, return_exceptions=True):
        assert isinstance(result, FlightSearchError)
    assert (await cache.get_or_fetch("k", fetch))[0].price == 83
    assert fetch.calls == 2


async def test_stopping_the_only_search_cancels_its_request():
    cache, fetch = ResultCache(), Fetcher([offer(83)], release=asyncio.Event())
    search = asyncio.create_task(cache.get_or_fetch("k", fetch))
    await asyncio.sleep(0)
    search.cancel()
    with pytest.raises(asyncio.CancelledError):
        await search
    await asyncio.sleep(0)
    assert fetch.cancelled and len(cache) == 0


async def test_stopping_one_search_keeps_the_request_for_the_other():
    release = asyncio.Event()
    cache, fetch = ResultCache(), Fetcher([offer(83)], release=release)
    stopped = asyncio.create_task(cache.get_or_fetch("k", fetch))
    kept = asyncio.create_task(cache.get_or_fetch("k", fetch))
    await asyncio.sleep(0)
    stopped.cancel()
    await asyncio.sleep(0)
    release.set()
    assert (await kept)[0].price == 83
    assert not fetch.cancelled and len(cache) == 1


async def test_provider_sends_one_google_request_for_repeated_searches():
    requests = 0

    def handler(request):
        nonlocal requests
        requests += 1
        return httpx.Response(200, text=results_page())

    provider = FastFlightsProvider(client=mock_client(handler))
    for _ in range(3):
        assert [o.price for o in await provider.search_flights("SKG", "VIE", "2026-10-31")] == [45.0]
    await provider.search_flights("SKG", "VIE", "2026-10-31", direct_only=True)
    assert requests == 2  # the direct-only search is a different search
    await provider.close()


async def test_provider_does_not_cache_failed_searches():
    responses = [httpx.Response(500), httpx.Response(200, text=results_page())]
    provider = FastFlightsProvider(client=mock_client(lambda request: responses.pop(0)))
    with pytest.raises(FlightSearchError):
        await provider.search_flights("SKG", "VIE", "2026-10-31")
    assert [o.price for o in await provider.search_flights("SKG", "VIE", "2026-10-31")] == [45.0]
    await provider.close()
