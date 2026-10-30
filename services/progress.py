import logging
import time
from typing import Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# (queries done, total queries, estimated seconds left)
OnProgress = Callable[[int, int, float], Awaitable[None]]


class Progress:
    """Counts finished queries in a batch and reports a time estimate, at most every `interval` seconds.

    Query times vary a lot, so each new estimate of the finish time is averaged with
    the previous one. That keeps the countdown ticking down instead of jumping around.
    """

    def __init__(self, total: int, on_progress: Optional[OnProgress], seconds_per_query: float,
                 interval: float = 3.0) -> None:
        self.total = total
        self.done = 0
        self._on_progress = on_progress
        self._initial_estimate = total * seconds_per_query
        self._interval = interval
        self._started = self._last_report = time.perf_counter()
        self._finish = self._started + self._initial_estimate

    async def start(self) -> None:
        await self._report(self._initial_estimate)

    async def track(self, awaitable: Awaitable[T]) -> T:
        result = await awaitable
        self.done += 1
        now = time.perf_counter()
        if self.done < self.total and now - self._last_report >= self._interval:
            self._last_report = now
            measured_finish = now + (now - self._started) / self.done * (self.total - self.done)
            self._finish = (self._finish + measured_finish) / 2
            await self._report(max(0.0, self._finish - now))
        return result

    async def _report(self, seconds_left: float) -> None:
        if self._on_progress:
            try:
                await self._on_progress(self.done, self.total, seconds_left)
            except Exception:
                logger.exception("Progress callback failed")
