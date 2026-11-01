import logging
import time
from typing import Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# (queries done, total queries, estimated seconds left)
OnProgress = Callable[[int, int, float], Awaitable[None]]
# Seconds left counting other jobs sharing the request slots (given searches about to start), or None.
Estimate = Callable[[int], Optional[float]]


class Progress:
    """Counts finished queries in a batch and reports a time estimate, at most every `interval` seconds.

    With `estimate`, the time left comes from the request scheduler, which knows this batch
    speeds up once smaller jobs sharing the slots finish. Without it, the batch's own speed so
    far is extrapolated, which overestimates while other jobs run alongside it.

    Query times vary a lot, so each new estimate of the finish time is averaged with
    the previous one. That keeps the countdown ticking down instead of jumping around.
    """

    def __init__(self, total: int, on_progress: Optional[OnProgress], seconds_per_query: float,
                 interval: float = 3.0, estimate: Optional[Estimate] = None) -> None:
        self.total = total
        self.done = 0
        self._on_progress = on_progress
        self._estimate = estimate
        self._initial_estimate = total * seconds_per_query
        self._interval = interval
        self._started = self._last_report = time.perf_counter()
        self._finish = self._started + self._initial_estimate

    async def start(self) -> None:
        predicted = self._estimate(self.total) if self._estimate else None  # nothing queued yet
        if predicted is not None:
            self._initial_estimate = predicted
            self._finish = self._started + predicted
        await self._report(self._initial_estimate)

    async def track(self, awaitable: Awaitable[T]) -> T:
        result = await awaitable
        self.done += 1
        now = time.perf_counter()
        if self.done < self.total and now - self._last_report >= self._interval:
            self._last_report = now
            predicted = self._estimate(0) if self._estimate else None
            if predicted is None:
                predicted = (now - self._started) / self.done * (self.total - self.done)
            self._finish = (self._finish + now + predicted) / 2
            await self._report(max(0.0, self._finish - now))
        return result

    async def _report(self, seconds_left: float) -> None:
        if self._on_progress:
            try:
                await self._on_progress(self.done, self.total, seconds_left)
            except Exception:
                logger.exception("Progress callback failed")
