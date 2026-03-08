import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from .config import settings

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
    )


async def close_redis() -> None:
    if _redis:
        await _redis.aclose()


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised")
    return _redis


class EhSemaphore:
    """
    Redis-based global semaphore for E-Hentai concurrent image request limiting.

    Uses a Redis counter with INCR/DECR + polling.
    Ensures at most EH_MAX_CONCURRENCY outgoing requests to E-H at any time,
    across all API instances.
    """

    _COUNTER_KEY = "eh:semaphore:count"

    def __init__(self) -> None:
        self.max_count = settings.eh_max_concurrency
        self.acquire_timeout = settings.eh_acquire_timeout

    @asynccontextmanager
    async def acquire(self):
        r = get_redis()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.acquire_timeout

        while True:
            count = await r.incr(self._COUNTER_KEY)
            if count <= self.max_count:
                try:
                    yield
                finally:
                    await r.decr(self._COUNTER_KEY)
                return

            # Slot not available — give it back and wait
            await r.decr(self._COUNTER_KEY)
            if loop.time() >= deadline:
                raise TimeoutError(f"EH semaphore: could not acquire slot within {self.acquire_timeout}s")
            await asyncio.sleep(0.3)


eh_semaphore = EhSemaphore()


class DownloadSemaphore:
    """
    Redis-based per-source download concurrency limiter.
    Uses INCR/DECR + polling, same pattern as EhSemaphore.
    """

    _LIMITS: dict[str, int] = {
        "ehentai": 2,
        "pixiv": 2,
        "other": 2,
    }

    def __init__(self, source: str, acquire_timeout: int = 300) -> None:
        self._key = f"download:sem:{source}"
        self.max_count = self._LIMITS.get(source, 2)
        self.acquire_timeout = acquire_timeout

    @asynccontextmanager
    async def acquire(self):
        r = get_redis()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.acquire_timeout

        while True:
            count = await r.incr(self._key)
            if count <= self.max_count:
                try:
                    yield
                finally:
                    await r.decr(self._key)
                return

            await r.decr(self._key)
            if loop.time() >= deadline:
                raise TimeoutError(f"Download semaphore [{self._key}]: could not acquire slot within {self.acquire_timeout}s")
            await asyncio.sleep(0.5)
