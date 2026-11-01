"""Decides which waiting Google request gets the next free slot.

The bot sends at most a few requests at a time. When more are waiting, first come first
served made a long digest block everyone queued behind it, including a user's one-off
/search. Instead:

1. Searches someone is waiting for (/search, /explore) go before background work
   (digests, tracker checks).
2. Within each group, 4 of every 5 slots go to the job with the fewest searches left, so
   small jobs finish fast; the 5th rotates through the other jobs, so every job keeps
   moving and none starves.
3. A search several jobs are waiting on (the cache lets a job join a search another job
   already started) counts for all of them, so it moves at the most urgent one's pace.
   Otherwise a small job waiting on a big job's search would wait at the big job's pace.

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
from typing import AsyncIterator, Awaitable, Iterator, Optional, TypeVar

ROTATE_EVERY = 5  # every 5th slot in a group goes to a job other than the shortest

T = TypeVar("T")


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


@dataclass(eq=False)
class _Ticket:
    """One request waiting for a slot, filed under every job waiting on it."""
    future: asyncio.Future
    scheduler: "SlotScheduler"
    share: Optional["SharedSearch"]
    owners: list[SearchJob] = field(default_factory=list)
    state: str = "waiting"  # then "granted" or "cancelled"


class SharedSearch:
    """The jobs waiting on one search. The cache starts each search inside one and adds every
    job that joins it later, so the search's queued requests count for all of those jobs."""

    def __init__(self, job: Optional[SearchJob]) -> None:
        self.jobs = [job] if job else []
        self.tickets: list[_Ticket] = []

    def add(self, job: Optional[SearchJob]) -> None:
        if job is None or job in self.jobs:
            return
        self.jobs.append(job)
        for ticket in self.tickets:
            if ticket.state == "waiting":
                ticket.scheduler._add_owner(ticket, job)

    async def run(self, work: Awaitable[T]) -> T:
        token = CURRENT_SHARE.set(self)  # the tasks the search starts inherit it
        try:
            return await work
        finally:
            CURRENT_SHARE.reset(token)


CURRENT_SHARE: ContextVar[Optional[SharedSearch]] = ContextVar("farebot_shared_search", default=None)


@dataclass
class _Group:
    """Waiting requests of one kind (interactive or background), per job in arrival order.
    Requests that were granted or stopped are dropped lazily when they reach the front."""
    queues: dict[SearchJob, deque[_Ticket]] = field(default_factory=dict)
    granted: int = 0
    rotation: int = 0


class SlotScheduler:
    def __init__(self, slots: int) -> None:
        self._free = slots
        self._groups = {True: _Group(), False: _Group()}
        self._untagged = SearchJob("untagged", interactive=False)
        self._jobs: dict[SearchJob, None] = {}  # every job seen, for finish estimates (ordered set)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        ticket = await self._acquire()
        owners = list(ticket.owners)
        for job in owners:
            job.running += 1
        try:
            yield
        finally:
            for job in owners:
                job.running -= 1
            self._release()

    async def _acquire(self) -> _Ticket:
        share = CURRENT_SHARE.get()
        owners = share.jobs if share and share.jobs else [CURRENT_JOB.get() or self._untagged]
        ticket = _Ticket(asyncio.get_running_loop().create_future(), self, share)
        for job in list(owners):
            self._add_owner(ticket, job)
        if share:
            share.tickets.append(ticket)
        self._dispatch()
        try:
            await ticket.future
        except asyncio.CancelledError:
            if ticket.state == "granted":
                self._release()  # the slot arrived just as we were cancelled: pass it on
            else:
                self._finish(ticket, "cancelled")
            raise
        return ticket

    def finish_in(self, job: SearchJob, rate: float, upcoming: int = 0) -> float:
        """Seconds until the job's requests are done, if no new jobs arrive.

        Plays the scheduling rule forward over every job's remaining requests, with all slots
        together completing `rate` requests per second. Unlike extrapolating the job's own speed
        so far, this knows it will speed up once smaller or interactive jobs ahead of it finish.
        `upcoming` counts requests the job is about to queue.
        """
        for other in [j for j in self._jobs if j.left == 0]:
            del self._jobs[other]
        left = {j: float(j.left) for j in self._jobs}
        left[job] = left.get(job, 0.0) + upcoming
        elapsed = 0.0
        while left.get(job, 0.0) > 1e-9:
            shares = _shares(left)
            step = min(left[j] / (share * rate) for j, share in shares.items())
            for j, share in shares.items():
                left[j] -= share * rate * step
            elapsed += step
            left = {j: n for j, n in left.items() if n > 1e-9}
        return elapsed

    def _add_owner(self, ticket: _Ticket, job: SearchJob) -> None:
        self._jobs[job] = None
        ticket.owners.append(job)
        job.waiting += 1
        self._groups[job.interactive].queues.setdefault(job, deque()).append(ticket)

    def _finish(self, ticket: _Ticket, state: str) -> None:
        ticket.state = state
        for job in ticket.owners:
            job.waiting -= 1
        if ticket.share:
            ticket.share.tickets.remove(ticket)

    def _release(self) -> None:
        self._free += 1
        self._dispatch()

    def _dispatch(self) -> None:
        while self._free > 0:
            ticket = self._pick()
            if ticket is None:
                return
            self._finish(ticket, "granted")
            self._free -= 1
            ticket.future.set_result(None)

    def _pick(self) -> Optional[_Ticket]:
        """The next waiting request: interactive first, then the hybrid rule within the group."""
        for interactive in (True, False):
            group = self._groups[interactive]
            for job, queue in list(group.queues.items()):
                while queue and queue[0].state != "waiting":
                    queue.popleft()
                if not queue:
                    del group.queues[job]
            if not group.queues:
                continue
            jobs = list(group.queues)
            job = min(jobs, key=lambda j: j.left)  # ties go to the job that queued first
            group.granted += 1
            if group.granted % ROTATE_EVERY == 0 and len(jobs) > 1:
                others = [j for j in jobs if j is not job]
                job = others[group.rotation % len(others)]
                group.rotation += 1
            return group.queues[job][0]
        return None


def _shares(left: dict[SearchJob, float]) -> dict[SearchJob, float]:
    """Each job's share of the slots under the rule above: interactive jobs take everything;
    within a group the shortest gets 4/5 and the rest split the rotating 1/5."""
    for interactive in (True, False):
        jobs = [j for j in left if j.interactive == interactive]
        if not jobs:
            continue
        if len(jobs) == 1:
            return {jobs[0]: 1.0}
        shortest = min(jobs, key=lambda j: left[j])
        rest = 1 / ROTATE_EVERY / (len(jobs) - 1)
        return {j: 1 - 1 / ROTATE_EVERY if j is shortest else rest for j in jobs}
    return {}
