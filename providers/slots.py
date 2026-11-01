"""Decides which waiting Google request gets the next free slot.

The bot sends at most a few requests at a time. When more are waiting, first come first
served made a long digest block everyone queued behind it, including a user's one-off
/search. Instead:

1. Searches someone is waiting for (/search, /explore) go before background work
   (digests, tracker checks).
2. Within each group, 4 of every 5 slots go to the job with the fewest searches left, so
   small jobs finish fast; the 5th rotates through the other jobs, so every job keeps
   moving and none starves.

Simulated on 5 and 20 simultaneous digests, this cut the average wait by about a third
against first come first served, stayed within ~10% of pure shortest-first, and no job
waited more than seconds for its first result. Google sees exactly the same load: only
the order changes.
"""
import asyncio
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, Optional

ROTATE_EVERY = 5  # every 5th slot in a group goes to a job other than the shortest


@dataclass(eq=False)
class SearchJob:
    """What a search belongs to: one user's /search or /explore, one digest, one tracker check."""
    name: str
    interactive: bool
    waiting: int = 0
    running: int = 0

    @property
    def left(self) -> int:
        return self.waiting + self.running


CURRENT_JOB: ContextVar[Optional[SearchJob]] = ContextVar("farebot_search_job", default=None)


@contextmanager
def search_job(name: str, interactive: bool) -> Iterator[SearchJob]:
    """Searches started inside this block (and the tasks it creates) belong to one job."""
    job = SearchJob(name, interactive)
    token = CURRENT_JOB.set(job)
    try:
        yield job
    finally:
        CURRENT_JOB.reset(token)


@dataclass
class _Group:
    """Waiting requests of one kind (interactive or background), per job in arrival order."""
    queues: dict[SearchJob, deque[asyncio.Future]] = field(default_factory=dict)
    granted: int = 0
    rotation: int = 0


class SlotScheduler:
    def __init__(self, slots: int) -> None:
        self._free = slots
        self._groups = {True: _Group(), False: _Group()}
        self._untagged = SearchJob("untagged", interactive=False)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        job = CURRENT_JOB.get() or self._untagged
        await self._acquire(job)
        job.running += 1
        try:
            yield
        finally:
            job.running -= 1
            self._release()

    async def _acquire(self, job: SearchJob) -> None:
        if self._free > 0 and not self._waiting():
            self._free -= 1
            return
        future = asyncio.get_running_loop().create_future()
        self._groups[job.interactive].queues.setdefault(job, deque()).append(future)
        job.waiting += 1
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self._release()  # the slot arrived just as we were cancelled: pass it on
            else:
                self._forget(job, future)
            raise

    def _release(self) -> None:
        self._free += 1
        while self._free > 0:
            picked = self._pick()
            if picked is None:
                return
            job, future = picked
            if future.cancelled():
                continue  # its task was stopped while waiting; _forget never saw it
            self._free -= 1
            future.set_result(None)

    def _pick(self) -> Optional[tuple[SearchJob, asyncio.Future]]:
        """The next waiting request: interactive first, then the hybrid rule within the group."""
        for interactive in (True, False):
            group = self._groups[interactive]
            if not group.queues:
                continue
            jobs = list(group.queues)
            shortest = min(jobs, key=lambda j: j.left)  # ties go to the job that queued first
            group.granted += 1
            job = shortest
            if group.granted % ROTATE_EVERY == 0 and len(jobs) > 1:
                others = [j for j in jobs if j is not shortest]
                job = others[group.rotation % len(others)]
                group.rotation += 1
            queue = group.queues[job]
            future = queue.popleft()
            job.waiting -= 1
            if not queue:
                del group.queues[job]
            return job, future
        return None

    def _forget(self, job: SearchJob, future: asyncio.Future) -> None:
        group = self._groups[job.interactive]
        queue = group.queues.get(job)
        if queue is None or future not in queue:
            return  # already taken off the queue by _release
        queue.remove(future)
        job.waiting -= 1
        if not queue:
            del group.queues[job]

    def _waiting(self) -> bool:
        return any(group.queues for group in self._groups.values())
