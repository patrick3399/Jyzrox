"""Tests for the application log viewer endpoints."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Log Levels ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_log_levels_defaults(client, mock_redis):
    """GET /api/logs/levels returns INFO for both when no Redis keys set."""
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.get("/api/logs/levels")
    assert resp.status_code == 200
    data = resp.json()
    assert data["levels"]["api"] == "INFO"
    assert data["levels"]["worker"] == "INFO"


@pytest.mark.asyncio
async def test_get_log_levels_from_redis(client, mock_redis):
    """GET /api/logs/levels reads stored levels from Redis."""

    async def fake_get(key):
        if key == "log_level:api":
            return b"DEBUG"
        if key == "log_level:worker":
            return b"ERROR"
        return None

    mock_redis.get = AsyncMock(side_effect=fake_get)
    resp = await client.get("/api/logs/levels")
    assert resp.status_code == 200
    data = resp.json()
    assert data["levels"]["api"] == "DEBUG"
    assert data["levels"]["worker"] == "ERROR"


@pytest.mark.asyncio
async def test_set_log_level_api(client, mock_redis):
    """PATCH /api/logs/levels stores level in Redis and returns updated."""
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.publish = AsyncMock(return_value=1)
    resp = await client.patch("/api/logs/levels", json={"source": "api", "level": "DEBUG"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "api"
    assert data["level"] == "DEBUG"


@pytest.mark.asyncio
async def test_set_log_level_publishes_change(client, mock_redis):
    """PATCH /api/logs/levels publishes to log_level:changed channel."""
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.publish = AsyncMock(return_value=1)
    await client.patch("/api/logs/levels", json={"source": "worker", "level": "WARNING"})
    # Check that publish was called with the right channel
    publish_calls = [c for c in mock_redis.publish.call_args_list if "log_level:changed" in str(c)]
    assert len(publish_calls) >= 1


@pytest.mark.asyncio
async def test_set_log_level_invalid_returns_422(client, mock_redis):
    """Invalid level or source is rejected with 422."""
    resp = await client.patch("/api/logs/levels", json={"source": "api", "level": "INVALID"})
    assert resp.status_code == 422
    resp2 = await client.patch("/api/logs/levels", json={"source": "nginx", "level": "INFO"})
    assert resp2.status_code == 422


# ── Log Entries ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_logs_empty(client, mock_redis):
    """GET /api/logs with empty list returns empty response."""
    mock_redis.lrange = AsyncMock(return_value=[])
    resp = await client.get("/api/logs/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["logs"] == []
    assert data["total"] == 0
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_get_logs_with_entries(client, mock_redis):
    """GET /api/logs returns entries from Redis."""
    entries = [
        json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "main",
                "message": "Hello",
                "timestamp": "2026-03-17T10:00:00+00:00",
            }
        ).encode(),
        json.dumps(
            {
                "level": "ERROR",
                "source": "worker",
                "logger": "worker",
                "message": "Oops",
                "timestamp": "2026-03-17T10:01:00+00:00",
            }
        ).encode(),
    ]
    mock_redis.lrange = AsyncMock(return_value=entries)
    resp = await client.get("/api/logs/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["logs"]) == 2
    assert data["logs"][0]["message"] == "Hello"


@pytest.mark.asyncio
async def test_get_logs_level_filter(client, mock_redis):
    """Level filter returns only matching entries."""
    entries = [
        json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "a",
                "message": "info msg",
                "timestamp": "2026-03-17T10:00:00+00:00",
            }
        ).encode(),
        json.dumps(
            {
                "level": "ERROR",
                "source": "api",
                "logger": "b",
                "message": "error msg",
                "timestamp": "2026-03-17T10:01:00+00:00",
            }
        ).encode(),
        json.dumps(
            {
                "level": "DEBUG",
                "source": "api",
                "logger": "c",
                "message": "debug msg",
                "timestamp": "2026-03-17T10:02:00+00:00",
            }
        ).encode(),
    ]
    mock_redis.lrange = AsyncMock(return_value=entries)
    resp = await client.get("/api/logs/?level=ERROR")
    data = resp.json()
    assert data["total"] == 1
    assert data["logs"][0]["level"] == "ERROR"


@pytest.mark.asyncio
async def test_get_logs_source_filter(client, mock_redis):
    """Source filter returns only matching entries."""
    entries = [
        json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "a",
                "message": "api msg",
                "timestamp": "2026-03-17T10:00:00+00:00",
            }
        ).encode(),
        json.dumps(
            {
                "level": "INFO",
                "source": "worker",
                "logger": "b",
                "message": "worker msg",
                "timestamp": "2026-03-17T10:01:00+00:00",
            }
        ).encode(),
    ]
    mock_redis.lrange = AsyncMock(return_value=entries)
    resp = await client.get("/api/logs/?source=worker")
    data = resp.json()
    assert data["total"] == 1
    assert data["logs"][0]["source"] == "worker"


@pytest.mark.asyncio
async def test_get_logs_keyword_search(client, mock_redis):
    """Search filter matches message content."""
    entries = [
        json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "a",
                "message": "User logged in",
                "timestamp": "2026-03-17T10:00:00+00:00",
            }
        ).encode(),
        json.dumps(
            {
                "level": "ERROR",
                "source": "api",
                "logger": "b",
                "message": "Connection failed",
                "timestamp": "2026-03-17T10:01:00+00:00",
            }
        ).encode(),
    ]
    mock_redis.lrange = AsyncMock(return_value=entries)
    resp = await client.get("/api/logs/?search=connection")
    data = resp.json()
    assert data["total"] == 1
    assert "Connection" in data["logs"][0]["message"]


@pytest.mark.asyncio
async def test_get_logs_pagination(client, mock_redis):
    """Limit and offset work correctly."""
    entries = [
        json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "a",
                "message": f"msg {i}",
                "timestamp": f"2026-03-17T10:{i:02d}:00+00:00",
            }
        ).encode()
        for i in range(5)
    ]
    mock_redis.lrange = AsyncMock(return_value=entries)
    resp = await client.get("/api/logs/?limit=2&offset=0")
    data = resp.json()
    assert len(data["logs"]) == 2
    assert data["total"] == 5
    assert data["has_more"] is True

    resp2 = await client.get("/api/logs/?limit=2&offset=4")
    data2 = resp2.json()
    assert len(data2["logs"]) == 1
    assert data2["has_more"] is False


@pytest.mark.asyncio
async def test_clear_logs(client, mock_redis):
    """DELETE /api/logs clears the list."""
    mock_redis.llen = AsyncMock(return_value=42)
    mock_redis.delete = AsyncMock(return_value=1)
    resp = await client.delete("/api/logs/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deleted"] == 42


@pytest.mark.asyncio
async def test_logs_requires_admin(make_client):
    """Non-admin users get 403."""
    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.get("/api/logs/levels")
        assert resp.status_code == 403
        resp2 = await ac.get("/api/logs/")
        assert resp2.status_code == 403


# ── Retention ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_retention_get_defaults(client, mock_redis):
    """GET /api/logs/retention returns defaults when no Redis keys set."""
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.get("/api/logs/retention")
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_entries"] == 2000


@pytest.mark.asyncio
async def test_log_retention_patch(client, mock_redis):
    """PATCH /api/logs/retention persists values to Redis."""
    mock_redis.set = AsyncMock(return_value=True)
    # After PATCH, _get_int_setting reads back from Redis; return None so defaults apply
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.patch("/api/logs/retention", json={"max_entries": 5000})
    assert resp.status_code == 200
    # Verify set was called for the max_entries key
    set_keys = [str(c) for c in mock_redis.set.call_args_list]
    assert any("log_max_entries" in k for k in set_keys)


@pytest.mark.asyncio
async def test_log_retention_patch_partial(client, mock_redis):
    """PATCH /api/logs/retention with only one field only updates that field."""
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    resp = await client.patch("/api/logs/retention", json={"max_entries": 3000})
    assert resp.status_code == 200
    set_keys = [str(c) for c in mock_redis.set.call_args_list]
    assert any("log_max_entries" in k for k in set_keys)
    # retention_days was not provided, so set should NOT have been called for it
    assert not any("log_retention_days" in k for k in set_keys)


# ── RedisLogHandler unit ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_log_handler_emit(mock_redis):
    """Unit test: RedisLogHandler writes to Redis via pipeline."""
    from core.log_handler import RedisLogHandler
    import logging

    handler = RedisLogHandler(source="api")
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Create a mock pipeline that is used directly (not as a context manager)
    mock_pipe = MagicMock()
    mock_pipe.lpush = MagicMock()
    mock_pipe.publish = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        payload = json.dumps(
            {
                "level": "INFO",
                "source": "api",
                "logger": "test",
                "message": "hello",
                "timestamp": "2026-03-17T10:00:00",
            }
        )
        await handler._async_emit(payload)

    mock_pipe.lpush.assert_called_once()
    mock_pipe.publish.assert_called_once()
    mock_pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_redis_log_handler_emit_trimming(mock_redis):
    """RedisLogHandler issues ltrim every _TRIM_INTERVAL emits."""
    import core.log_handler as lh
    from core.log_handler import RedisLogHandler, _TRIM_INTERVAL
    import logging

    # Reset counter to force trim on next emit
    lh._trim_counter = _TRIM_INTERVAL - 1

    handler = RedisLogHandler(source="api")
    handler.setFormatter(logging.Formatter("%(message)s"))

    mock_pipe = MagicMock()
    mock_pipe.lpush = MagicMock()
    mock_pipe.publish = MagicMock()
    mock_pipe.ltrim = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1, 1])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        payload = json.dumps(
            {
                "level": "DEBUG",
                "source": "api",
                "logger": "test",
                "message": "trim test",
                "timestamp": "2026-03-17T10:00:00",
            }
        )
        await handler._async_emit(payload)

    mock_pipe.ltrim.assert_called_once()
    assert lh._trim_counter == 0


# ── install_log_handler extra_loggers ───────────────────────────────


def test_install_log_handler_attaches_to_extra_loggers():
    """install_log_handler attaches RedisLogHandler to each name in extra_loggers."""
    import logging
    from core.log_handler import install_log_handler, RedisLogHandler

    root_logger = logging.getLogger()
    extra1 = logging.getLogger("fake.extra1")
    extra2 = logging.getLogger("fake.extra2")

    # Capture handler counts before the call so we can find the newly added one.
    root_before = len(root_logger.handlers)
    extra1_before = len(extra1.handlers)
    extra2_before = len(extra2.handlers)

    try:
        install_log_handler("test", extra_loggers=["fake.extra1", "fake.extra2"])

        # Root logger must have gained exactly one RedisLogHandler.
        new_root = [h for h in root_logger.handlers[root_before:] if isinstance(h, RedisLogHandler)]
        assert len(new_root) == 1, "Root logger should have one new RedisLogHandler"

        # Both named loggers must have gained a RedisLogHandler directly.
        new_extra1 = [h for h in extra1.handlers[extra1_before:] if isinstance(h, RedisLogHandler)]
        assert len(new_extra1) == 1, "fake.extra1 should have a RedisLogHandler attached"

        new_extra2 = [h for h in extra2.handlers[extra2_before:] if isinstance(h, RedisLogHandler)]
        assert len(new_extra2) == 1, "fake.extra2 should have a RedisLogHandler attached"

    finally:
        # Remove every RedisLogHandler added during this test to prevent leakage.
        for logger in (root_logger, extra1, extra2):
            for h in list(logger.handlers):
                if isinstance(h, RedisLogHandler):
                    logger.removeHandler(h)


def test_non_propagating_logger_reaches_handler():
    """install_log_handler directly attaches to a non-propagating logger so it still receives records."""
    import logging
    from core.log_handler import install_log_handler, RedisLogHandler

    noprop = logging.getLogger("fake.noprop")
    noprop.propagate = False
    noprop_before = len(noprop.handlers)

    root_logger = logging.getLogger()
    root_before = len(root_logger.handlers)

    try:
        install_log_handler("test", extra_loggers=["fake.noprop"])

        # The handler is attached directly to the non-propagating logger,
        # so records emitted on it will reach the handler regardless of propagate.
        new_handlers = [h for h in noprop.handlers[noprop_before:] if isinstance(h, RedisLogHandler)]
        assert len(new_handlers) == 1, "RedisLogHandler must be directly attached to a non-propagating logger"
        # Confirm propagate is still False — the direct attachment is what matters.
        assert noprop.propagate is False

    finally:
        noprop.propagate = True  # restore default
        for logger in (root_logger, noprop):
            for h in list(logger.handlers):
                if isinstance(h, RedisLogHandler):
                    logger.removeHandler(h)
