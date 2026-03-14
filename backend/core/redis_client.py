import asyncio
import json
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


async def is_rate_limit_boosted() -> bool:
    """Return True if downloads should run at full speed (no rate limiting delays)."""
    r = get_redis()
    override = await r.get("rate_limit:override:unlocked")
    if override is not None:
        return True
    active = await r.get("rate_limit:schedule:active")
    mode = await r.get("rate_limit:schedule:mode")
    if active in (b"1", "1") and (mode is None or mode in (b"full_speed", "full_speed")):
        return True
    return False


async def get_download_delay(source: str, default_ms: int = 0) -> float:
    """Read per-source delay from Redis, return seconds. Returns 0 if boost mode active."""
    if await is_rate_limit_boosted():
        return 0.0
    r = get_redis()
    val = await r.get(f"rate_limit:config:{source}:delay_ms")
    if val is not None:
        try:
            return int(val) / 1000.0
        except (ValueError, TypeError):
            pass
    return default_ms / 1000.0


async def get_typed_download_delay(source: str, delay_type: str, default_ms: int = 0) -> float:
    """Read per-source typed delay from Redis (e.g., page_delay_ms, pagination_delay_ms).
    Returns 0 if boost mode active."""
    if await is_rate_limit_boosted():
        return 0.0
    r = get_redis()
    val = await r.get(f"rate_limit:config:{source}:{delay_type}_delay_ms")
    if val is not None:
        try:
            return int(val) / 1000.0
        except (ValueError, TypeError):
            pass
    return default_ms / 1000.0


async def get_image_concurrency(source: str, default: int = 1) -> int:
    """Read per-source image concurrency from Redis, falling back to default."""
    r = get_redis()
    val = await r.get(f"rate_limit:config:{source}:image_concurrency")
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return default


class EhSemaphore:
    """
    Redis-based global semaphore for E-Hentai concurrent image request limiting.

    Uses a Redis counter with INCR/DECR + polling.
    Ensures at most EH_MAX_CONCURRENCY outgoing requests to E-H at any time,
    across all API instances.
    """

    _COUNTER_KEY = "eh:semaphore:count"

    def __init__(self) -> None:
        self.acquire_timeout = settings.eh_acquire_timeout

    @asynccontextmanager
    async def acquire(self):
        r = get_redis()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.acquire_timeout

        val = await r.get("rate_limit:config:ehentai:concurrency")
        if val is not None:
            try:
                max_count = int(val)
            except (ValueError, TypeError):
                max_count = settings.eh_max_concurrency
        else:
            max_count = settings.eh_max_concurrency

        while True:
            count = await r.incr(self._COUNTER_KEY)
            if count <= max_count:
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
        "gallery_dl": 2,
    }

    def __init__(self, source: str, acquire_timeout: int = 300, max_count: int | None = None) -> None:
        self._key = f"download:sem:{source}"
        self.max_count = max_count if max_count is not None else self._LIMITS.get(source, 2)
        self.acquire_timeout = acquire_timeout

    @classmethod
    async def get_limit(cls, source: str, default: int = 2) -> int:
        """Read concurrency limit from Redis, falling back to _LIMITS dict then default."""
        r = get_redis()
        val = await r.get(f"rate_limit:config:{source}:concurrency")
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        base = source.split(":")[0] if ":" in source else source
        return cls._LIMITS.get(source, cls._LIMITS.get(base, default))

    @asynccontextmanager
    async def acquire(self):
        r = get_redis()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.acquire_timeout

        while True:
            count = await r.incr(self._key)
            # Set TTL as safety net — if worker crashes, counter auto-expires
            await r.expire(self._key, 7200)
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


async def publish_job_event(event: dict) -> None:
    """Publish a job event to the download:events channel."""
    try:
        await get_redis().publish("download:events", json.dumps(event))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("publish_job_event failed: %s", exc)


def get_pubsub():
    """Return a new PubSub object for subscribing to channels."""
    return get_redis().pubsub()
