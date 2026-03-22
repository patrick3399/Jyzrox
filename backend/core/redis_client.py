import asyncio
import json
import time
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
        loop = asyncio.get_running_loop()
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
    """Redis-based per-source download concurrency limiter.

    Uses a sorted set where member=job_id, score=last_heartbeat_time.
    Stale entries (no heartbeat for >timeout seconds) are auto-evicted on acquire.
    """

    _LIMITS: dict[str, int] = {
        "ehentai": 2,
        "pixiv": 2,
        "gallery_dl": 2,
    }

    # Lua: atomic evict-stale + check-capacity + add
    _ACQUIRE_LUA = """
    local key = KEYS[1]
    local max = tonumber(ARGV[1])
    local job_id = ARGV[2]
    local now = tonumber(ARGV[3])
    local stale = now - tonumber(ARGV[4])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', stale)
    if redis.call('ZCARD', key) < max then
        redis.call('ZADD', key, now, job_id)
        return 1
    end
    return 0
    """

    # Lua: atomic check-exists + update-score
    _HEARTBEAT_LUA = """
    local key = KEYS[1]
    local job_id = ARGV[1]
    local now = tonumber(ARGV[2])
    if redis.call('ZSCORE', key, job_id) then
        redis.call('ZADD', key, now, job_id)
        return 1
    end
    return 0
    """

    def __init__(self, source: str, acquire_timeout: int = 300, max_count: int | None = None) -> None:
        self._key = f"download:sem:{source}"
        self.max_count = max_count if max_count is not None else self._LIMITS.get(source, 2)
        self.acquire_timeout = acquire_timeout
        self._stale_threshold = 300  # evict entries with no heartbeat for 5 min

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

    async def acquire(self, job_id: str, timeout: int | None = None) -> float:
        """Try to acquire a slot. Polls until acquired or timeout.

        Returns the total seconds spent waiting.
        Raises TimeoutError if slot not acquired within timeout.
        """
        r = get_redis()
        _timeout = timeout if timeout is not None else self.acquire_timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _timeout
        wait_start = loop.time()

        while True:
            now = time.time()
            acquired = await r.eval(
                self._ACQUIRE_LUA,
                1,
                self._key,
                str(self.max_count),
                job_id,
                str(now),
                str(self._stale_threshold),
            )
            if acquired:
                from core.events import EventType, emit_safe

                await emit_safe(EventType.SEMAPHORE_CHANGED, source=self._key, action="acquire", job_id=job_id)
                return loop.time() - wait_start

            if loop.time() >= deadline:
                raise TimeoutError(f"Download semaphore [{self._key}]: could not acquire slot within {_timeout}s")
            await asyncio.sleep(0.5)

    async def release(self, job_id: str) -> None:
        """Release a slot by removing the job from the sorted set."""
        r = get_redis()
        await r.zrem(self._key, job_id)
        from core.events import EventType, emit_safe

        await emit_safe(EventType.SEMAPHORE_CHANGED, source=self._key, action="release", job_id=job_id)

    async def heartbeat(self, job_id: str) -> bool:
        """Update heartbeat timestamp. Returns False if job was evicted (not in set)."""
        r = get_redis()
        now = time.time()
        result = await r.eval(self._HEARTBEAT_LUA, 1, self._key, job_id, str(now))
        return bool(result)

    @classmethod
    async def get_info(cls, source: str) -> dict:
        """Return semaphore usage info for a single source."""
        sem = cls(source)
        r = get_redis()
        used = await r.zcard(sem._key)
        max_count = await cls.get_limit(source)
        return {"used": used, "max": max_count}

    @classmethod
    async def get_all_active(cls) -> dict[str, dict]:
        """Return semaphore info for all sources that have active semaphore keys."""
        r = get_redis()
        # Collect all keys first
        all_keys: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match="download:sem:*", count=100)
            for key in keys:
                all_keys.append(key.decode() if isinstance(key, bytes) else key)
            if cursor == 0:
                break
        if not all_keys:
            return {}
        # Pipeline: zcard + concurrency limit for each key
        pipe = r.pipeline(transaction=False)
        sources: list[str] = []
        for key_str in all_keys:
            source = key_str.removeprefix("download:sem:")
            sources.append(source)
            pipe.zcard(key_str)
            pipe.get(f"rate_limit:config:{source}:concurrency")
        raw = await pipe.execute()
        result: dict[str, dict] = {}
        for i, source in enumerate(sources):
            used = raw[i * 2] or 0
            limit_raw = raw[i * 2 + 1]
            base = source.split(":")[0] if ":" in source else source
            max_count = int(limit_raw) if limit_raw else cls._LIMITS.get(source, cls._LIMITS.get(base, 2))
            result[source] = {"used": used, "max": max_count}
        return result

    @asynccontextmanager
    async def acquire_ctx(self, job_id: str):
        """Backward-compatible context manager wrapper."""
        await self.acquire(job_id)
        try:
            yield
        finally:
            await self.release(job_id)


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
            )
        else:
            # Unknown type — publish directly to old channel as fallback
            await get_redis().publish("download:events", json.dumps(event))
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("publish_job_event failed: %s", exc)


def get_pubsub():
    """Return a new PubSub object for subscribing to channels."""
    return get_redis().pubsub()
