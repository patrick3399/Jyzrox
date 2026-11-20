import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from .config import settings

logger = logging.getLogger(__name__)

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
    return active in (b"1", "1") and (mode is None or mode in (b"full_speed", "full_speed"))


async def get_download_delay(source: str, default_ms: int = 0) -> float:
    """Read per-source delay from Redis, return seconds. Returns 0 if boost mode active."""
    if await is_rate_limit_boosted():
        return 0.0
    r = get_redis()
    val = await r.get(f"rate_limit:config:{source}:delay_ms")
    if val is not None:
        try:
            return int(val) / 1000.0
        except ValueError, TypeError:
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
        except ValueError, TypeError:
            pass
    return default_ms / 1000.0


async def get_image_concurrency(source: str, default: int = 1) -> int:
    """Read per-source image concurrency from Redis, falling back to default."""
    r = get_redis()
    val = await r.get(f"rate_limit:config:{source}:image_concurrency")
    if val is not None:
        try:
            return int(val)
        except ValueError, TypeError:
            pass
    return default


class EhSemaphore:
    """
    Redis-based global semaphore for E-Hentai browse requests (image proxy and
    on-demand pToken lookups), shared by every API process.

    Each holder owns a lease: a member of a sorted set scored by its expiry.
    Acquire atomically evicts expired leases and adds one while fewer than the
    limit remain; release removes the holder's own lease. A holder that never
    releases (its process killed mid-request by a deploy, or its release lost to
    a Redis error or a cancellation) frees its slot when the lease lapses.

    This replaced an INCR/DECR counter with no owner or expiry, under which every
    missed DECR leaked a slot for good: production sat at 6 of 8 slots taken
    with no EH traffic at all, so readers queued behind two usable slots.
    """

    _LEASES_KEY = "eh:semaphore:leases"
    # A holder makes at most two EH requests (image page, then image), each
    # bounded by a 30 s request timeout. A lease only outlives its holder when
    # the release was lost, so this bounds how long a lost slot stays taken.
    LEASE_SECONDS = 120

    # Lua: atomic evict-expired + check-capacity + add. The key expires with the
    # last lease so an idle semaphore leaves nothing behind.
    _ACQUIRE_LUA = """
    local key = KEYS[1]
    local max = tonumber(ARGV[1])
    local token = ARGV[2]
    local now = tonumber(ARGV[3])
    local expires = tonumber(ARGV[4])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
    if redis.call('ZCARD', key) < max then
        redis.call('ZADD', key, expires, token)
        redis.call('EXPIRE', key, tonumber(ARGV[5]))
        return 1
    end
    return 0
    """

    def __init__(self) -> None:
        self.acquire_timeout = settings.eh_acquire_timeout

    @asynccontextmanager
    async def acquire(self):
        r = get_redis()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.acquire_timeout

        # Deliberately a distinct Redis key from `rate_limit:config:ehentai:concurrency`
        # (that one belongs to DownloadSemaphore, see `get_limit()` below). Sharing a
        # key coupled the interactive reader's throughput to background download job
        # concurrency, which is wrong — they are different bottlenecks.
        val = await r.get("rate_limit:config:ehentai:browse_concurrency")
        if val is not None:
            try:
                max_count = int(val)
            except ValueError, TypeError:
                max_count = settings.eh_max_concurrency
        else:
            max_count = settings.eh_max_concurrency

        token = uuid.uuid4().hex
        while True:
            now = time.time()
            acquired = await r.eval(
                self._ACQUIRE_LUA,
                1,
                self._LEASES_KEY,
                str(max_count),
                token,
                str(now),
                str(now + self.LEASE_SECONDS),
                str(self.LEASE_SECONDS),
            )
            if acquired:
                break
            if loop.time() >= deadline:
                raise TimeoutError(f"EH semaphore: could not acquire slot within {self.acquire_timeout}s")
            await asyncio.sleep(0.3)

        try:
            yield
        finally:
            try:
                await r.zrem(self._LEASES_KEY, token)
            except aioredis.RedisError as exc:
                # The lease lapses on its own; the request itself already finished.
                logger.warning("EH semaphore release failed, slot frees in %ss: %s", self.LEASE_SECONDS, exc)


eh_semaphore = EhSemaphore()


async def publish_job_event(event: dict) -> None:
    """Publish a job event — delegates to EventBus while maintaining backward compatibility.

    Existing callers pass dicts like:
      {"type": "job_update", "job_id": "...", "status": "...", "progress": {...}, "user_id": ...}
      {"type": "subscription_checked", "sub_id": ..., "status": "...", "job_id": ..., "user_id": ...}
    """
    try:
        from core.events import EventType, emit

        event_type_str = event.get("type", "")
        user_id = event.get("user_id")

        if event_type_str == "job_update":
            status = event.get("status", "")
            status_map = {
                "queued": EventType.DOWNLOAD_ENQUEUED,
                "running": EventType.DOWNLOAD_STARTED,
                "done": EventType.DOWNLOAD_COMPLETED,
                "failed": EventType.DOWNLOAD_FAILED,
                "cancelled": EventType.DOWNLOAD_CANCELLED,
                "paused": EventType.DOWNLOAD_PAUSED,
                "partial": EventType.DOWNLOAD_FAILED,
            }
            et = status_map.get(status)
            if et is None:
                import logging as _log

                _log.getLogger(__name__).warning(
                    "publish_job_event: unknown status %r, using DOWNLOAD_PROGRESS", status
                )
                et = EventType.DOWNLOAD_PROGRESS
            await emit(
                et,
                actor_user_id=user_id,
                resource_type="download_job",
                resource_id=event.get("job_id"),
                status=status,
                progress=event.get("progress"),
            )
        elif event_type_str == "subscription_checked":
            await emit(
                EventType.SUBSCRIPTION_CHECKED,
                actor_user_id=user_id,
                resource_type="subscription",
                resource_id=event.get("sub_id"),
                status=event.get("status"),
                new_works=event.get("new_works", 0),
                job_id=event.get("job_id"),
            )
        elif event_type_str == "subscription_checking":
            await emit(
                EventType.SUBSCRIPTION_CHECKING,
                actor_user_id=user_id,
                resource_type="subscription",
                resource_id=event.get("sub_id"),
            )
        else:
            # Unknown type — publish directly to old channel as fallback
            await get_redis().publish("download:events", json.dumps(event))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("publish_job_event failed: %s", exc)


_LAZY_REEXPORTS = {
    "DownloadSemaphore": "core.redis_semaphores",
    "get_pubsub": "core.redis_pubsub",
    "pubsub_listen_forever": "core.redis_pubsub",
}


def __getattr__(name: str):
    # core.redis_semaphores / core.redis_pubsub import get_redis from this module,
    # so their names are resolved on first access instead of at import time.
    module_name = _LAZY_REEXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)
