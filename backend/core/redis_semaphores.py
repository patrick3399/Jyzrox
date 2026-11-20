"""Per-source download concurrency limiter (Redis sorted set + Lua)."""

import asyncio
import time
from contextlib import asynccontextmanager

from core.redis_client import get_redis


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
            except ValueError, TypeError:
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
        await r.zremrangebyscore(sem._key, "-inf", time.time() - sem._stale_threshold)
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
        now = time.time()
        for key_str in all_keys:
            source = key_str.removeprefix("download:sem:")
            sources.append(source)
            pipe.zremrangebyscore(key_str, "-inf", now - cls(source)._stale_threshold)
            pipe.zcard(key_str)
            pipe.get(f"rate_limit:config:{source}:concurrency")
        raw = await pipe.execute()
        result: dict[str, dict] = {}
        for i, source in enumerate(sources):
            used = raw[i * 3 + 1] or 0
            limit_raw = raw[i * 3 + 2]
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
