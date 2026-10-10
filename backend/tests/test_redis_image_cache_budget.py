"""Regression coverage for the image-cache budget inside the control-plane Redis.

Incident 2026-10-10: Redis sat at 767.98M / 768M under `noeviction`. 770 MB of it
was proxied image bytes, about 1 MB was sessions, locks and queue state, and
every write was being rejected. These tests pin the two mechanisms that keep the
cache from getting there: trimming the oldest image bytes, and refusing to admit
new ones near the limit.
"""

from unittest.mock import AsyncMock

DAY = 86400
PREFIXES = {"thumb:proxied:": DAY, "thumb:cdn:": DAY, "pixiv:img:": DAY}


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, bytes]] = []

    def ttl(self, key: bytes) -> None:
        self._ops.append(("ttl", key))

    def strlen(self, key: bytes) -> None:
        self._ops.append(("strlen", key))

    async def execute(self) -> list[int]:
        out: list[int] = []
        for op, key in self._ops:
            entry = self._redis.store.get(key)
            if op == "ttl":
                out.append(-2 if entry is None else entry[1])
            else:
                out.append(0 if entry is None else len(entry[0]))
        return out


class FakeRedis:
    """Just enough Redis for the trim: SCAN with paging, TTL/STRLEN, UNLINK."""

    def __init__(self) -> None:
        self.store: dict[bytes, tuple[bytes, int]] = {}
        self.scan_calls = 0

    def put(self, key: str, size: int, ttl: int) -> None:
        self.store[key.encode()] = (b"x" * size, ttl)

    async def scan(self, cursor: int, match: str = "*", count: int = 10):
        self.scan_calls += 1
        prefix = match.rstrip("*").encode()
        keys = sorted(k for k in self.store if k.startswith(prefix))
        page = keys[cursor : cursor + count]
        next_cursor = cursor + count if cursor + count < len(keys) else 0
        return next_cursor, page

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    async def unlink(self, *keys: bytes) -> int:
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    def names(self) -> set[str]:
        return {key.decode() for key in self.store}


def _seeded() -> FakeRedis:
    redis = FakeRedis()
    # Image bytes, oldest first. Remaining TTL shrinks as a key ages.
    redis.put("thumb:proxied:1:1", size=100, ttl=100)  # written 23h58m ago
    redis.put("thumb:cdn:aaa", size=100, ttl=50_000)
    redis.put("pixiv:img:bbb", size=100, ttl=80_000)
    redis.put("thumb:proxied:1:2", size=100, ttl=86_000)  # written 6m40s ago
    # Control plane and small JSON caches: never the trim's business.
    redis.put("session:1:tok", size=50, ttl=1_000)
    redis.put("saq:job:interactive:cron:x", size=50, ttl=30)
    redis.put("cron:library_scan:enabled", size=1, ttl=-1)
    redis.put("setting:eh_use_ex", size=1, ttl=-1)
    redis.put("eh:imagelist:1", size=500, ttl=600_000)
    return redis


async def test_trim_image_cache_deletes_the_oldest_written_keys_first_until_the_target_is_freed():
    from services.redis_memory import trim_image_cache

    redis = _seeded()

    result = await trim_image_cache(redis, PREFIXES, bytes_to_free=150)

    assert "thumb:proxied:1:1" not in redis.names()
    assert "thumb:cdn:aaa" not in redis.names()
    assert {"pixiv:img:bbb", "thumb:proxied:1:2"} <= redis.names()
    assert result == {"scanned": 4, "deleted_keys": 2, "freed_bytes": 200, "truncated": False}


async def test_trim_image_cache_asked_to_free_everything_never_touches_control_plane_or_json_cache_keys():
    from services.redis_memory import trim_image_cache

    redis = _seeded()

    result = await trim_image_cache(redis, PREFIXES, bytes_to_free=10**9)

    assert redis.names() == {
        "session:1:tok",
        "saq:job:interactive:cron:x",
        "cron:library_scan:enabled",
        "setting:eh_use_ex",
        "eh:imagelist:1",
    }
    assert result["deleted_keys"] == 4


async def test_trim_image_cache_with_nothing_to_free_does_not_scan():
    from services.redis_memory import trim_image_cache

    redis = _seeded()

    result = await trim_image_cache(redis, PREFIXES, bytes_to_free=0)

    assert redis.scan_calls == 0
    assert result == {"scanned": 0, "deleted_keys": 0, "freed_bytes": 0, "truncated": False}


async def test_trim_image_cache_stops_scanning_at_the_key_cap_and_reports_truncated():
    from services.redis_memory import trim_image_cache

    redis = FakeRedis()
    for page in range(6):
        redis.put(f"thumb:proxied:9:{page}", size=10, ttl=1_000 + page)

    result = await trim_image_cache(redis, PREFIXES, bytes_to_free=10**9, max_keys=4, batch_size=2)

    assert result["truncated"] is True
    assert result["scanned"] == 4
    assert result["deleted_keys"] == 4
    assert len(redis.names()) == 2


async def test_trim_image_cache_skips_keys_without_a_ttl_under_an_image_prefix():
    """A key we did not write (no TTL) has no age to rank by; leave it alone."""
    from services.redis_memory import trim_image_cache

    redis = FakeRedis()
    redis.put("thumb:cdn:manual", size=100, ttl=-1)
    redis.put("thumb:cdn:old", size=100, ttl=10)

    await trim_image_cache(redis, PREFIXES, bytes_to_free=10**9)

    assert redis.names() == {"thumb:cdn:manual"}


def _memory_info(used: int, maxmemory: int):
    async def info(section: str):
        if section == "memory":
            return {"used_memory": used, "maxmemory": maxmemory, "maxmemory_policy": "noeviction"}
        return {"evicted_keys": 0}

    return AsyncMock(side_effect=info)


async def test_image_cache_writes_are_refused_at_the_admission_watermark():
    from services.redis_memory import image_cache_writes_admitted

    redis = AsyncMock()
    redis.info = _memory_info(used=90, maxmemory=100)

    assert await image_cache_writes_admitted(redis, 90.0) is False


async def test_image_cache_writes_are_admitted_below_the_admission_watermark():
    from services.redis_memory import image_cache_writes_admitted

    redis = AsyncMock()
    redis.info = _memory_info(used=89, maxmemory=100)

    assert await image_cache_writes_admitted(redis, 90.0) is True


async def test_admission_decision_is_reused_within_the_memo_window_instead_of_sampling_per_write():
    from services.redis_memory import image_cache_writes_admitted

    redis = AsyncMock()
    redis.info = _memory_info(used=10, maxmemory=100)

    for _ in range(50):
        await image_cache_writes_admitted(redis, 90.0)

    # One sample reads two INFO sections.
    assert redis.info.await_count == 2


async def test_admission_fails_open_when_redis_memory_cannot_be_sampled():
    from services.redis_memory import image_cache_writes_admitted

    redis = AsyncMock()
    redis.info = AsyncMock(side_effect=ConnectionError("redis down"))

    assert await image_cache_writes_admitted(redis, 90.0) is True


async def test_admission_fails_open_when_redis_has_no_maxmemory_to_measure_against():
    from services.redis_memory import image_cache_writes_admitted

    redis = AsyncMock()
    redis.info = _memory_info(used=10**12, maxmemory=0)

    assert await image_cache_writes_admitted(redis, 90.0) is True
