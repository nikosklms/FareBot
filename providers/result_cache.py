import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Hashable, List, Optional

from providers.base import FlightOffer
from providers.slots import CURRENT_JOB, SharedSearch

# Prices on Google Flights change a few times a day at most; 15 minutes old is still the price a user would see.
CACHE_SECONDS = 15 * 60
# At ~430 searches a minute the bot can't store more than ~6,500 within 15 minutes, so this limit
# rarely applies; it only bounds memory (about 13 KB per search, so at most ~100 MB).
MAX_ENTRIES = 8000


@dataclass
class _Running:
    task: asyncio.Future
    share: SharedSearch  # the jobs waiting on this search, for the request scheduler
    waiters: int = 0
    keep: bool = True


class ResultCache:
    """Recent search results shared by every user, so repeated searches skip Google.

    A search that is already running is shared as well: a second identical search waits
    for the first instead of sending its own request. Failed searches aren't stored, and
    neither are results the fetch marks incomplete with keep_out().
    """

    def __init__(self, ttl: float = CACHE_SECONDS, max_entries: int = MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        # Oldest first, so expired entries are always at the front.
        self._entries: OrderedDict[Hashable, tuple[float, List[FlightOffer]]] = OrderedDict()
        self._running: dict[Hashable, _Running] = {}
        self.hits = 0
        self.shared = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    async def get_or_fetch(self, key: Hashable,
                           fetch: Callable[[], Awaitable[Optional[List[FlightOffer]]]]) -> Optional[List[FlightOffer]]:
        self._drop_expired()
        entry = self._entries.get(key)
        if entry is not None:
            self.hits += 1
            return list(entry[1])

        running = self._running.get(key)
        if running is None:
            self.misses += 1
            share = SharedSearch(CURRENT_JOB.get())
            running = _Running(asyncio.ensure_future(share.run(fetch())), share)
            self._running[key] = running
            running.task.add_done_callback(lambda task: self._finished(key, running))
        else:
            self.shared += 1
            # Tell the scheduler this job waits on the search too, so a small job joining a big
            # job's search isn't served at the big job's pace.
            running.share.add(CURRENT_JOB.get())

        running.waiters += 1
        try:
            result = await asyncio.shield(running.task)
        except asyncio.CancelledError:
            # Stop the request only when nobody else is waiting for it (e.g. the user pressed Stop).
            running.waiters -= 1
            if running.waiters == 0:
                running.task.cancel()
                # Forget it now, not when the cancellation completes, so a search arriving
                # in between starts its own request instead of joining a cancelled one.
                if self._running.get(key) is running:
                    del self._running[key]
            raise
        running.waiters -= 1
        return list(result) if result is not None else None

    def keep_out(self, key: Hashable) -> None:
        """Don't store the result of the running search for key (e.g. it's incomplete)."""
        running = self._running.get(key)
        if running is not None:
            running.keep = False

    def _finished(self, key: Hashable, running: _Running) -> None:
        task = running.task
        if self._running.get(key) is running:
            del self._running[key]
        if task.cancelled() or task.exception() is not None or task.result() is None or not running.keep:
            return
        self._entries.pop(key, None)
        self._entries[key] = (self._clock(), task.result())
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def _drop_expired(self) -> None:
        cutoff = self._clock() - self._ttl
        while self._entries:
            stored_at = next(iter(self._entries.values()))[0]
            if stored_at > cutoff:
                break
            self._entries.popitem(last=False)
