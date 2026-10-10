"""
Tests for services/cache.py — Redis caching helpers.

Strategy:
- Patch `services.cache.get_redis` to return an AsyncMock Redis object.
- No HTTP client or DB needed; these are pure unit tests.
- Each test constructs its own mock so return values are explicit.
"""

import json
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(**overrides) -> AsyncMock:
    """Return an AsyncMock Redis with sensible defaults for every method used
    by services.cache.  Individual tests override only what they need."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.lpush = AsyncMock(return_value=1)
    r.ltrim = AsyncMock(return_value=True)
    r.lrange = AsyncMock(return_value=[])
    r.lrem = AsyncMock(return_value=1)
    r.info = AsyncMock(
        return_value={"used_memory": 0, "maxmemory": 0, "maxmemory_policy": "noeviction", "evicted_keys": 0}
    )
    for attr, value in overrides.items():
        setattr(r, attr, value)
    return r


# ---------------------------------------------------------------------------
# get_json / set_json
# ---------------------------------------------------------------------------


async def test_get_json_key_exists_returns_parsed_value():
    """get_json should decode the raw bytes and return the parsed object."""
    payload = {"title": "test gallery", "pages": 42}
    redis = _make_redis(get=AsyncMock(return_value=json.dumps(payload).encode()))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_json

        result = await get_json("eh:gallery:1")

    assert result == payload
    redis.get.assert_awaited_once_with("eh:gallery:1")


async def test_get_json_key_missing_returns_none():
    """get_json should return None when Redis.get returns None."""
    redis = _make_redis(get=AsyncMock(return_value=None))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_json

        result = await get_json("eh:gallery:missing")

    assert result is None


async def test_set_json_calls_setex_with_correct_args():
    """set_json should call Redis.setex with the key, TTL, and JSON-encoded value."""
    redis = _make_redis()
    payload = {"gid": 99, "token": "abc"}

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_json

        await set_json("eh:gallery:99", payload, ttl=86400)

    redis.setex.assert_awaited_once_with(
        "eh:gallery:99",
        86400,
        json.dumps(payload, ensure_ascii=False),
    )


async def test_set_json_non_ascii_content_preserved():
    """set_json must not escape non-ASCII characters (ensure_ascii=False)."""
    redis = _make_redis()
    payload = {"title": "日本語タイトル", "artist": "作家名"}

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_json

        await set_json("eh:gallery:7", payload, ttl=300)

    _args, _kwargs = redis.setex.await_args
    stored_str = _args[2]
    # Non-ASCII characters must appear verbatim — not as \uXXXX escapes
    assert "日本語タイトル" in stored_str
    assert "作家名" in stored_str


# ---------------------------------------------------------------------------
# get_bytes / set_bytes
# ---------------------------------------------------------------------------


async def test_set_bytes_stores_normal_data():
    """set_bytes should call Redis.setex when the payload is within the 5 MB limit."""
    redis = _make_redis()
    data = b"fake image bytes" * 100  # well under 5 MB

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_bytes

        await set_bytes("thumb:proxied:1:0", data, ttl=86400)

    redis.setex.assert_awaited_once_with("thumb:proxied:1:0", 86400, data)


async def test_set_bytes_skips_oversized_data_without_error():
    """set_bytes must silently skip and NOT call setex when len(value) > 5 MB."""
    redis = _make_redis()
    oversized = b"x" * (5 * 1024 * 1024 + 1)  # one byte over the limit

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_bytes

        await set_bytes("thumb:proxied:1:0", oversized, ttl=86400)

    redis.setex.assert_not_awaited()


async def test_get_bytes_key_exists_returns_bytes():
    """get_bytes should return raw bytes from Redis when the key exists."""
    raw = b"\x89PNG\r\n\x1a\n"
    redis = _make_redis(get=AsyncMock(return_value=raw))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_bytes

        result = await get_bytes("thumb:proxied:2:0")

    assert result == raw
    redis.get.assert_awaited_once_with("thumb:proxied:2:0")


async def test_get_bytes_key_missing_returns_none():
    """get_bytes should return None when the key does not exist in Redis."""
    redis = _make_redis(get=AsyncMock(return_value=None))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_bytes

        result = await get_bytes("thumb:proxied:missing")

    assert result is None


# ---------------------------------------------------------------------------
# Cache writes are best-effort (incident 2026-10-10: Redis at maxmemory)
# ---------------------------------------------------------------------------

_OOM_MESSAGE = "command not allowed when used memory > 'maxmemory'."


def _memory_info(used: int, maxmemory: int) -> AsyncMock:
    return AsyncMock(
        return_value={
            "used_memory": used,
            "maxmemory": maxmemory,
            "maxmemory_policy": "noeviction",
            "evicted_keys": 0,
        }
    )


async def test_set_bytes_when_redis_rejects_the_write_at_maxmemory_does_not_raise():
    """A full Redis must cost the cache entry, not the request that fetched the image."""
    from redis.exceptions import OutOfMemoryError

    redis = _make_redis(setex=AsyncMock(side_effect=OutOfMemoryError(_OOM_MESSAGE)))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_bytes

        await set_bytes("thumb:proxied:1:0", b"image", ttl=86400)

    redis.setex.assert_awaited_once()


async def test_set_json_when_redis_rejects_the_write_at_maxmemory_does_not_raise():
    from redis.exceptions import OutOfMemoryError

    redis = _make_redis(setex=AsyncMock(side_effect=OutOfMemoryError(_OOM_MESSAGE)))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_json

        await set_json("eh:gallery:1", {"title": "x"}, ttl=300)

    redis.setex.assert_awaited_once()


async def test_push_system_alert_when_redis_rejects_the_write_at_maxmemory_does_not_raise():
    """Alerts are raised from error paths; failing to store one must not mask the error."""
    from redis.exceptions import OutOfMemoryError

    redis = _make_redis(lpush=AsyncMock(side_effect=OutOfMemoryError(_OOM_MESSAGE)))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import push_system_alert

        await push_system_alert("E-Hentai cookie invalid or expired")

    redis.lpush.assert_awaited_once()


async def test_set_bytes_at_the_admission_watermark_skips_the_write():
    """Image bytes stop being admitted at 90% so the control plane keeps its room."""
    redis = _make_redis(info=_memory_info(used=90, maxmemory=100))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_bytes

        await set_bytes("thumb:proxied:1:0", b"image", ttl=86400)

    redis.setex.assert_not_awaited()


async def test_set_bytes_below_the_admission_watermark_writes():
    redis = _make_redis(info=_memory_info(used=89, maxmemory=100))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_bytes

        await set_bytes("thumb:proxied:1:0", b"image", ttl=86400)

    redis.setex.assert_awaited_once_with("thumb:proxied:1:0", 86400, b"image")


async def test_set_json_at_the_admission_watermark_still_writes():
    """Only image bytes are gated: JSON caches are kilobytes and hold pTokens worth keeping."""
    redis = _make_redis(info=_memory_info(used=95, maxmemory=100))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import set_json

        await set_json("eh:imagelist:1", {"1": "tok"}, ttl=604800)

    redis.setex.assert_awaited_once()


async def test_cdn_thumb_roundtrip_uses_the_thumb_cdn_prefix_and_24h_ttl():
    redis = _make_redis(get=AsyncMock(return_value=b"thumb"))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_cdn_thumb, set_cdn_thumb

        await set_cdn_thumb("abc123", b"thumb")
        result = await get_cdn_thumb("abc123")

    redis.setex.assert_awaited_once_with("thumb:cdn:abc123", 86400, b"thumb")
    redis.get.assert_awaited_once_with("thumb:cdn:abc123")
    assert result == b"thumb"


def test_image_cache_prefix_registry_covers_every_set_bytes_caller():
    """The trim only knows the prefixes listed here; a new image cache must be added."""
    from services.cache import IMAGE_CACHE_TTLS

    assert IMAGE_CACHE_TTLS == {"thumb:proxied:": 86400, "thumb:cdn:": 86400, "pixiv:img:": 86400}


# ---------------------------------------------------------------------------
# push_system_alert / get_system_alerts / clear_system_alerts
# ---------------------------------------------------------------------------


async def test_push_system_alert_calls_lpush_and_ltrim():
    """push_system_alert must lpush the message then ltrim to keep at most 50 entries."""
    redis = _make_redis()

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import push_system_alert

        await push_system_alert("disk usage above 90%")

    redis.lrange.assert_awaited_once_with("system:alerts", 0, 49)
    redis.lpush.assert_awaited_once_with("system:alerts", "disk usage above 90%")
    redis.ltrim.assert_awaited_once_with("system:alerts", 0, 49)


async def test_push_system_alert_skips_duplicate_message():
    """push_system_alert must not append a duplicate alert message."""
    redis = _make_redis(lrange=AsyncMock(return_value=[b"disk usage above 90%"]))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import push_system_alert

        await push_system_alert("disk usage above 90%")

    redis.lpush.assert_not_awaited()
    redis.ltrim.assert_not_awaited()


async def test_get_system_alerts_returns_decoded_list():
    """get_system_alerts should decode byte entries and return plain strings."""
    raw_alerts = [b"alert one", b"alert two", "already a string", b"alert one"]
    redis = _make_redis(lrange=AsyncMock(return_value=raw_alerts))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_system_alerts

        result = await get_system_alerts()

    assert result == ["alert one", "alert two", "already a string"]
    redis.lrange.assert_awaited_once_with("system:alerts", 0, 49)


async def test_get_system_alerts_empty_list():
    """get_system_alerts should return an empty list when no alerts exist."""
    redis = _make_redis(lrange=AsyncMock(return_value=[]))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_system_alerts

        result = await get_system_alerts()

    assert result == []


async def test_clear_system_alerts_calls_delete():
    """clear_system_alerts must delete the system:alerts key."""
    redis = _make_redis()

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import clear_system_alerts

        await clear_system_alerts()

    redis.delete.assert_awaited_once_with("system:alerts")


async def test_dismiss_system_alert_removes_all_matching_messages():
    """dismiss_system_alert removes all copies of the given alert message."""
    redis = _make_redis(lrem=AsyncMock(return_value=3))

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import dismiss_system_alert

        result = await dismiss_system_alert("alert one")

    assert result == 3
    redis.lrem.assert_awaited_once_with("system:alerts", 0, "alert one")


# ---------------------------------------------------------------------------
# Named cache operations — gallery roundtrip
# ---------------------------------------------------------------------------


async def test_gallery_cache_roundtrip_set_then_get():
    """set_gallery_cache followed by get_gallery_cache should preserve the data."""
    gallery_data = {
        "gid": 123456,
        "token": "abcdef1234",
        "title": "Test Gallery",
        "category": "Manga",
        "pages": 30,
    }
    encoded = json.dumps(gallery_data, ensure_ascii=False).encode()

    # The mock must return the same JSON that set_gallery_cache would have stored.
    redis = _make_redis(
        get=AsyncMock(return_value=encoded),
        setex=AsyncMock(return_value=True),
    )

    with patch("services.cache.get_redis", return_value=redis):
        from services.cache import get_gallery_cache, set_gallery_cache

        await set_gallery_cache(123456, gallery_data)
        result = await get_gallery_cache(123456)

    # Verify set used the expected key and TTL (86400 s = 24 h)
    setex_args, _ = redis.setex.await_args
    assert setex_args[0] == "eh:gallery:123456"
    assert setex_args[1] == 86400

    # Verify get used the expected key and round-tripped the value
    redis.get.assert_awaited_once_with("eh:gallery:123456")
    assert result == gallery_data
