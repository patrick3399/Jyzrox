"""Priority gate and dedicated decode pool for thumbnail generation."""

import asyncio
import concurrent.futures
import heapq
import itertools
from dataclasses import dataclass

from worker.helpers import env_int

# Decode priorities; the lower value is served first.
_PRIORITY_COVER = 0
_PRIORITY_BULK = 1


class _PrioritySemaphore:
    """Semaphore that serves waiters by priority, then by arrival.

    Every decode in the worker shares these slots. A full-gallery job queues a
    whole commit batch at once, so with plain FIFO a one-image cover job waited
    behind the pages of every gallery ahead of it. A cover now waits for the
    decode already in flight at most.
    """

    def __init__(self, size: int) -> None:
        self._free = size
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._arrival = itertools.count()

    async def acquire(self, priority: int) -> None:
        if self._free > 0:
            self._free -= 1
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._arrival), waiter))
        try:
            await waiter
        except asyncio.CancelledError:
            # release() may have handed this waiter the slot just before the
            # cancellation landed; pass it on or it is lost for good.
            if waiter.done() and not waiter.cancelled():
                self.release()
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, waiter = heapq.heappop(self._waiters)
            if not waiter.done():  # a cancelled waiter is skipped
                waiter.set_result(None)
                return
        self._free += 1


_thumbnail_semaphore: _PrioritySemaphore | None = None
_thumbnail_semaphore_size: int | None = None
_thumbnail_executor: concurrent.futures.ThreadPoolExecutor | None = None
_thumbnail_executor_size: int | None = None


@dataclass(frozen=True, slots=True)
class _ThumbnailResult:
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    phash: str | None = None
    phash_int: int | None = None
    phash_q0: int | None = None
    phash_q1: int | None = None
    phash_q2: int | None = None
    phash_q3: int | None = None
    thumbhash: str | None = None


def _thumbnail_workers() -> int:
    return env_int("THUMBNAIL_WORKERS", 1)


def _thumbnail_commit_batch() -> int:
    return env_int("THUMBNAIL_COMMIT_BATCH", 25)


def _get_thumbnail_semaphore() -> _PrioritySemaphore:
    global _thumbnail_semaphore, _thumbnail_semaphore_size

    size = _thumbnail_workers()
    if _thumbnail_semaphore is None or _thumbnail_semaphore_size != size:
        _thumbnail_semaphore = _PrioritySemaphore(size)
        _thumbnail_semaphore_size = size
    return _thumbnail_semaphore


def _get_thumbnail_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool so decode threads — and their glibc arenas — stay bounded.

    `asyncio.to_thread` dispatches to the process-wide default executor, which
    also serves file hashing and every other worker `to_thread` call, so decodes
    land on arbitrary threads. glibc gives each thread its own arena, and with
    `MALLOC_ARENA_MAX=2` two sequential decodes on two threads retain two
    full-size arenas — roughly 2.5 GB for a 100 MP source, past the 2 GB
    container cap. The semaphore below bounds how many decodes run at once but
    says nothing about how many threads they are spread across, which is why
    THUMBNAIL_WORKERS=1 alone did not stop the 2026-08-13 OOM kills.
    """
    global _thumbnail_executor, _thumbnail_executor_size

    size = _thumbnail_workers()
    if _thumbnail_executor is None or _thumbnail_executor_size != size:
        if _thumbnail_executor is not None:
            _thumbnail_executor.shutdown(wait=False)
        _thumbnail_executor = concurrent.futures.ThreadPoolExecutor(max_workers=size, thread_name_prefix="thumbnail")
        _thumbnail_executor_size = size
    return _thumbnail_executor
