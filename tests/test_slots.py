import asyncio

from providers.slots import CURRENT_JOB, SearchJob, SlotScheduler, search_job
from tests.fakes import USER_ID, future


async def run(scheduler: SlotScheduler, jobs: list[tuple[str, int, bool]]) -> list[str]:
    """Queue every job's searches in this order, then let them run; returns who got each slot, in order."""
    order: list[str] = []

    async def one(name: str) -> None:
        async with scheduler.slot():
            order.append(name)
            await asyncio.sleep(0)

    tasks = []
    for name, searches, interactive in jobs:
        with search_job(name, interactive):  # tasks created here belong to this job
            tasks += [asyncio.create_task(one(name)) for _ in range(searches)]
    await asyncio.gather(*tasks)
    return order


async def test_never_more_than_the_slots_at_once():
    scheduler, running, most = SlotScheduler(3), 0, 0

    async def one() -> None:
        nonlocal running, most
        async with scheduler.slot():
            running += 1
            most = max(most, running)
            await asyncio.sleep(0)
            running -= 1

    await asyncio.gather(*(one() for _ in range(20)))
    assert most == 3


async def test_a_search_someone_waits_for_goes_before_background_work():
    order = await run(SlotScheduler(1), [("digest", 20, False), ("/search", 1, True)])
    assert order[:2] == ["digest", "/search"]  # the digest's first search already had the slot


async def test_the_shortest_job_goes_first():
    order = await run(SlotScheduler(1), [("long digest", 20, False), ("short digest", 4, False)])
    assert order[:6].count("short digest") == 4  # queued later, finished first


async def test_every_fifth_slot_keeps_longer_jobs_moving():
    order = await run(SlotScheduler(1), [("long", 60, False), ("short", 30, False)])
    first_30 = order[1:31]
    assert first_30.count("long") >= 5  # never frozen, even while the shorter job is running


async def test_a_short_interactive_search_doesnt_wait_behind_a_long_explore():
    order = await run(SlotScheduler(1), [("explore", 30, True), ("/search", 1, True)])
    assert order[1] == "/search"


async def test_untagged_searches_still_run():
    scheduler = SlotScheduler(2)
    done = []

    async def one(i: int) -> None:
        async with scheduler.slot():
            done.append(i)

    await asyncio.gather(*(one(i) for i in range(6)))
    assert sorted(done) == list(range(6))


async def test_stopping_a_waiting_search_frees_its_place():
    scheduler, release = SlotScheduler(1), asyncio.Event()

    async def holder() -> None:
        async with scheduler.slot():
            await release.wait()

    async def waiter() -> None:
        async with scheduler.slot():
            pass

    held = asyncio.create_task(holder())
    await asyncio.sleep(0)
    stopped = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    stopped.cancel()  # e.g. the user pressed Stop
    await asyncio.gather(stopped, return_exceptions=True)
    release.set()
    await held
    await asyncio.wait_for(waiter(), timeout=1)  # the slot came back


async def test_a_slot_granted_to_a_search_being_stopped_is_passed_on():
    scheduler = SlotScheduler(1)
    job = SearchJob("digest", interactive=False)
    token = CURRENT_JOB.set(job)
    try:
        await scheduler._acquire()  # something holds the only slot
        waiting = asyncio.create_task(scheduler._acquire())
    finally:
        CURRENT_JOB.reset(token)
    await asyncio.sleep(0)
    scheduler._release()  # the holder finishes and hands the slot to the waiting search…
    waiting.cancel()  # …which is stopped before it can use it
    await asyncio.gather(waiting, return_exceptions=True)
    assert scheduler._free == 1 and job.waiting == 0


async def jobs_seen(bot, provider) -> list[SearchJob]:
    seen = []
    searches = provider.search_flights

    async def recording(*args, **kwargs):
        seen.append(CURRENT_JOB.get())
        return await searches(*args, **kwargs)

    provider.search_flights = recording
    return seen


async def test_user_searches_are_interactive_and_digests_and_trackers_are_not(bot, provider):
    from daemon.scheduler import check_tracker, send_digest
    seen = await jobs_seen(bot, provider)

    await bot.send(f"/search ATH LON {future(5)}")
    await bot.finish_background_task()
    await bot.send("/explore ATH oceania 1")
    await bot.finish_background_task()
    interactive = {job.interactive for job in seen}
    seen.clear()

    tracker = await bot.services.db.create_tracker(USER_ID, "ATH", "LON", future(5), 100.0)
    await check_tracker(bot.services, bot.app.bot, tracker.id)
    digest = await bot.services.db.create_digest(USER_ID, "ATH", "oceania", days_ahead=1)
    await send_digest(bot.services, bot.app.bot, digest.id)

    assert interactive == {True}
    assert seen and {job.interactive for job in seen} == {False}
    assert {job.name for job in seen} == {f"tracker #{tracker.id}", f"digest #{digest.id}"}


async def shared_searches(big_first: bool, small_interactive: bool = False) -> list[str]:
    """A big digest searches k0..k19; a small job needs k16..k19, at the end of the big one's queue."""
    from providers.base import FlightOffer
    from providers.result_cache import ResultCache
    cache, scheduler, order = ResultCache(), SlotScheduler(1), []

    def fetch(key: str):
        async def search():
            async with scheduler.slot():
                order.append(key)
                await asyncio.sleep(0)
            return [FlightOffer("ATH", "LON", "2026-12-01", price=1.0)]
        return search

    async def start(name: str, keys: list[str], interactive: bool) -> list[asyncio.Task]:
        with search_job(name, interactive):
            tasks = [asyncio.create_task(cache.get_or_fetch(key, fetch(key))) for key in keys]
        for _ in range(3):
            await asyncio.sleep(0)  # let the searches start and queue up
        return tasks

    big = ("big digest", [f"k{i}" for i in range(20)], False)
    small = ("small", [f"k{i}" for i in range(16, 20)], small_interactive)
    first, second = (big, small) if big_first else (small, big)
    tasks = await start(*first) + await start(*second)
    await asyncio.gather(*tasks)
    return order


SMALL = ("k16", "k17", "k18", "k19")


async def test_a_small_job_sharing_a_big_jobs_searches_gets_them_first():
    order = await shared_searches(big_first=True)  # the big job owns the shared searches
    # Done while the big job has run only a few of its own, not at positions 16-19 (its pace).
    assert max(order.index(key) for key in SMALL) < order.index("k5")
    assert len(order) == 20  # each shared search ran once


async def test_sharing_works_the_same_when_the_small_job_queues_first():
    order = await shared_searches(big_first=False)
    assert max(order.index(key) for key in SMALL) < order.index("k5") and len(order) == 20


async def test_an_interactive_search_sharing_a_digests_search_jumps_the_queue():
    order = await shared_searches(big_first=True, small_interactive=True)
    assert max(order.index(key) for key in SMALL) < order.index("k2")  # straight after what was already running
