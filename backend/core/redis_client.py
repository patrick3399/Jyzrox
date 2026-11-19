import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress

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


def get_pubsub():
    """Return a new PubSub object for subscribing to channels."""
    return get_redis().pubsub()


_PUBSUB_RETRY_START = 1.0
_PUBSUB_RETRY_MAX = 30.0


async def pubsub_listen_forever(
    channel: str,
    on_message,
    *,
    on_subscribe=None,
    name: str,
) -> None:
    """Subscribe to `channel` and dispatch messages until the task is cancelled.

    A Redis restart drops every subscription and redis-py does not resubscribe on
    its own, so a listener that treats a connection error as terminal goes deaf
    for the rest of the process lifetime without surfacing anything afterwards.
    This retries with exponential backoff instead.

    `on_subscribe` runs after every successful (re)subscribe, including the first.
    Messages published while the connection was down are lost with no way to
    replay them, so callers use this hook to resynchronise whatever state the
    channel keeps up to date.
    """
    import logging

    logger = logging.getLogger(__name__)
    backoff = _PUBSUB_RETRY_START

    while True:
        pubsub = None
        try:
            pubsub = get_pubsub()
            await pubsub.subscribe(channel)
            backoff = _PUBSUB_RETRY_START
            if on_subscribe is not None:
                await on_subscribe()
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    await on_message(message["data"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A single bad payload must not cost us the subscription.
                    logger.warning("[%s] Failed to process message: %s", name, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[%s] Pub/Sub connection lost (%s); resubscribing in %.2fs",
                name,
                exc,
                backoff,
            )
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.unsubscribe(channel)
                with suppress(Exception):
                    await pubsub.aclose()

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _PUBSUB_RETRY_MAX)
