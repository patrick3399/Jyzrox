"""
Unit tests for core.redis_client — connection lifecycle and utility functions.

Covers:
- get_redis() raises RuntimeError when _redis is None
- get_redis() returns the Redis instance when initialised
- init_redis() creates a Redis connection via aioredis.from_url
- close_redis() calls aclose() on the current Redis instance
- get_typed_download_delay() reads per-source typed delay; returns 0 when boosted
- publish_job_event() delegates to EventBus for known types; falls back to legacy channel for unknown types
- get_pubsub() returns a PubSub object from the Redis instance

Note: is_rate_limit_boosted(), get_download_delay(), get_image_concurrency(),
and DownloadSemaphore.get_limit() are already covered in test_rate_limits.py.
This file focuses on the connection-management functions and remaining helpers.

Implementation note on init_redis / close_redis:
  conftest.py replaces core.redis_client.init_redis and close_redis with
  AsyncMocks at session start so the test suite never connects to a real Redis
  server.  To test the actual implementations we temporarily stop those
  patches, run the test body against the real function, and then restart the
  patches so subsequent tests are unaffected.
"""

import json
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.redis_client as mod


@contextmanager
def _real_redis_fns():
    """Context manager that briefly restores init_redis and close_redis to their
    original implementations by stopping the conftest-level patches."""
    import sys as _sys
    _cf = _sys.modules.get("conftest") or _sys.modules.get("tests.conftest")
    if _cf is None:
        raise RuntimeError("conftest module not found in sys.modules")
    _cf._redis_init_patch.stop()
    _cf._redis_close_patch.stop()
    try:
        yield
    finally:
        _cf._redis_init_patch.start()
        _cf._redis_close_patch.start()


# ---------------------------------------------------------------------------
# get_redis()
# ---------------------------------------------------------------------------


def test_get_redis_raises_when_not_initialized():
    """get_redis() must raise RuntimeError when _redis has not been set."""
    original = mod._redis
    mod._redis = None
    try:
        with pytest.raises(RuntimeError, match="not initialised"):
            mod.get_redis()
    finally:
        mod._redis = original


def test_get_redis_returns_instance_when_initialized():
    """get_redis() must return the exact Redis object stored in _redis."""
    original = mod._redis
    mock_redis = AsyncMock()
    mod._redis = mock_redis
    try:
        assert mod.get_redis() is mock_redis
    finally:
        mod._redis = original


# ---------------------------------------------------------------------------
# init_redis()
# ---------------------------------------------------------------------------


async def test_init_redis_creates_connection_via_aioredis():
    """init_redis() must call aioredis.from_url and store the result in _redis."""
    original = mod._redis
    mod._redis = None
    fake_redis = AsyncMock()
    try:
        with _real_redis_fns():
            with patch("core.redis_client.aioredis.from_url", return_value=fake_redis) as mock_from_url:
                await mod.init_redis()
                mock_from_url.assert_called_once()
                assert mod._redis is fake_redis
    finally:
        mod._redis = original


async def test_init_redis_passes_redis_url_from_settings():
    """init_redis() must pass settings.redis_url as the first argument to from_url."""
    original = mod._redis
    mod._redis = None
    try:
        with _real_redis_fns():
            with patch("core.redis_client.aioredis.from_url", return_value=AsyncMock()) as mock_from_url:
                await mod.init_redis()
                call_args = mock_from_url.call_args
                redis_url = call_args[0][0]
                assert isinstance(redis_url, str)
                assert "://" in redis_url
    finally:
        mod._redis = original


# ---------------------------------------------------------------------------
# close_redis()
# ---------------------------------------------------------------------------


async def test_close_redis_calls_aclose_on_connection():
    """close_redis() must call aclose() on the stored Redis instance."""
    mock_redis = AsyncMock()
    original = mod._redis
    mod._redis = mock_redis
    try:
        with _real_redis_fns():
            await mod.close_redis()
        mock_redis.aclose.assert_awaited_once()
    finally:
        mod._redis = original


async def test_close_redis_is_noop_when_not_initialized():
    """close_redis() must not raise when _redis is None."""
    original = mod._redis
    mod._redis = None
    try:
        # Should complete without error
        await mod.close_redis()
    finally:
        mod._redis = original


# ---------------------------------------------------------------------------
# get_typed_download_delay()
# ---------------------------------------------------------------------------


async def test_get_typed_download_delay_reads_typed_key_from_redis():
    """get_typed_download_delay() must read {source}:{delay_type}_delay_ms and convert ms → s."""
    from core.redis_client import get_typed_download_delay

    mock_redis = AsyncMock()

    def _get(key):
        if key == "rate_limit:config:pixiv:page_delay_ms":
            return b"800"
        return None

    mock_redis.get = AsyncMock(side_effect=_get)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        result = await get_typed_download_delay("pixiv", "page", default_ms=0)

    assert result == pytest.approx(0.8)


async def test_get_typed_download_delay_returns_default_when_no_redis_key():
    """Returns default_ms / 1000 when no Redis key exists for the typed delay."""
    from core.redis_client import get_typed_download_delay

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        result = await get_typed_download_delay("pixiv", "pagination", default_ms=1500)

    assert result == pytest.approx(1.5)


async def test_get_typed_download_delay_returns_zero_when_boosted():
    """Returns 0.0 when override boost mode is active, regardless of Redis delay value."""
    from core.redis_client import get_typed_download_delay

    mock_redis = AsyncMock()

    def _get(key):
        if key == "rate_limit:override:unlocked":
            return b"1"
        if "delay_ms" in key:
            return b"3000"
        return None

    mock_redis.get = AsyncMock(side_effect=_get)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        result = await get_typed_download_delay("pixiv", "illust", default_ms=500)

    assert result == 0.0


async def test_get_typed_download_delay_falls_back_to_default_on_invalid_value():
    """Returns default_ms / 1000 when the Redis value cannot be parsed as int."""
    from core.redis_client import get_typed_download_delay

    mock_redis = AsyncMock()

    def _get(key):
        if key == "rate_limit:config:ehentai:page_delay_ms":
            return b"not_a_number"
        return None

    mock_redis.get = AsyncMock(side_effect=_get)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        result = await get_typed_download_delay("ehentai", "page", default_ms=2000)

    assert result == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# publish_job_event()
# ---------------------------------------------------------------------------


async def test_publish_job_event_delegates_job_update_to_event_bus():
    """publish_job_event() with type=job_update must delegate to EventBus pipeline,
    publishing to events:download.completed and events:all channels."""
    from unittest.mock import MagicMock
    from core.redis_client import publish_job_event

    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mock_pipe.publish = MagicMock(return_value=mock_pipe)
    mock_pipe.lpush = MagicMock(return_value=mock_pipe)
    mock_pipe.ltrim = MagicMock(return_value=mock_pipe)
    mock_pipe.execute = AsyncMock(return_value=[1, 1, 1, True])

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        await publish_job_event({"type": "job_update", "job_id": "abc123", "status": "done"})

    # EventBus uses a pipeline — verify publish calls were made
    mock_redis.pipeline.assert_called_once_with(transaction=False)
    publish_calls = mock_pipe.publish.call_args_list
    channels = [call.args[0] for call in publish_calls]
    assert "events:download.completed" in channels
    assert "events:all" in channels

    # Verify the payload includes the job_id as resource_id
    payloads = [json.loads(call.args[1]) for call in publish_calls]
    resource_ids = [p.get("resource_id") for p in payloads]
    assert "abc123" in resource_ids


async def test_publish_job_event_unknown_type_falls_back_to_download_events_channel():
    """publish_job_event() with an unknown type must fall back to publishing directly
    to the legacy download:events channel."""
    from core.redis_client import publish_job_event

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        await publish_job_event({"job_id": "abc123", "status": "done"})

    mock_redis.publish.assert_awaited_once()
    call_args = mock_redis.publish.call_args[0]
    assert call_args[0] == "download:events"
    published = json.loads(call_args[1])
    assert published["job_id"] == "abc123"
    assert published["status"] == "done"


async def test_publish_job_event_does_not_raise_when_redis_errors():
    """publish_job_event() must silently swallow exceptions from Redis pipeline failure."""
    from core.redis_client import publish_job_event

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(side_effect=ConnectionError("Redis down"))
    mock_redis.publish = AsyncMock(side_effect=ConnectionError("Redis down"))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        # Should not raise
        await publish_job_event({"type": "job_update", "job_id": "xyz", "status": "running"})


# ---------------------------------------------------------------------------
# get_pubsub()
# ---------------------------------------------------------------------------


def test_get_pubsub_returns_pubsub_from_redis_instance():
    """get_pubsub() must return the PubSub object produced by the Redis instance."""
    from core.redis_client import get_pubsub

    mock_pubsub = object()
    mock_redis = AsyncMock()
    mock_redis.pubsub = lambda: mock_pubsub

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        result = get_pubsub()

    assert result is mock_pubsub
