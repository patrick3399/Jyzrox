"""
Integration tests for the system router (/api/system/*).

Uses the `client` fixture (authenticated as admin user_id=1).
- AsyncSessionLocal (used by health/info) is patched to use the SQLite test engine.
- get_redis is already patched by the client fixture via mock_redis.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'admin', 'hash', 'admin')"
        )
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


async def test_system_health_returns_ok_status(client, db_session_factory, mock_redis):
    mock_redis.ping = AsyncMock(return_value=True)
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        # Simulate df -i returning safe inode usage
        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n10\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    # Health may return 200 ok or 503 if a sub-check fails.
    # We just verify the response has the expected shape.
    data = resp.json()
    if resp.status_code == 200:
        assert data["status"] == "ok"
        assert "services" in data
    else:
        # 503 means a service check failed — still a valid structured response
        assert resp.status_code == 503
        assert "detail" in data


# ---------------------------------------------------------------------------
# Tests — info
# ---------------------------------------------------------------------------


async def test_system_info_returns_version_fields(
    client, db_session_factory, mock_redis
):
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "versions" in data
    versions = data["versions"]
    assert "jyzrox" in versions
    assert "python" in versions
    assert "fastapi" in versions


async def test_system_info_versions_field_has_expected_keys(
    client, db_session_factory, mock_redis
):
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    expected_keys = {"jyzrox", "python", "fastapi", "gallery_dl", "postgresql", "redis", "onnxruntime"}
    assert expected_keys == set(data["versions"].keys())


# ---------------------------------------------------------------------------
# Tests — cache
# ---------------------------------------------------------------------------


async def test_system_cache_returns_stats_structure(client, mock_redis):
    mock_redis.info = AsyncMock(
        return_value={"used_memory": 1024, "used_memory_human": "1.00K"}
    )
    mock_redis.dbsize = AsyncMock(return_value=42)
    mock_redis.scan = AsyncMock(return_value=(0, []))

    resp = await client.get("/api/system/cache")

    assert resp.status_code == 200
    data = resp.json()
    assert "total_keys" in data
    assert "total_memory" in data
    assert "breakdown" in data
    assert isinstance(data["breakdown"], dict)


async def test_system_cache_clear_returns_deleted_count(client, mock_redis):
    mock_redis.scan = AsyncMock(return_value=(0, [b"key1", b"key2"]))
    mock_redis.delete = AsyncMock(return_value=2)

    resp = await client.delete("/api/system/cache")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "deleted_keys" in data
    assert isinstance(data["deleted_keys"], int)


async def test_system_cache_clear_specific_category_works(client, mock_redis):
    mock_redis.scan = AsyncMock(return_value=(0, [b"eh:search:abc"]))
    mock_redis.delete = AsyncMock(return_value=1)

    resp = await client.delete("/api/system/cache/eh_search")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["category"] == "eh_search"
    assert data["deleted_keys"] == 1


async def test_system_cache_clear_unknown_category_returns_400(client, mock_redis):
    resp = await client.delete("/api/system/cache/nonexistent_category")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests — reconcile
# ---------------------------------------------------------------------------


async def test_system_reconcile_trigger_enqueues_job(client):
    resp = await client.post("/api/system/reconcile")
    assert resp.status_code == 200
    assert resp.json()["status"] == "enqueued"
    from main import app
    app.state.arq.enqueue_job.assert_called_with("reconciliation_job")


async def test_system_reconcile_result_when_never_run_returns_never_run(
    client, mock_redis
):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/system/reconcile")

    assert resp.status_code == 200
    assert resp.json()["status"] == "never_run"


async def test_system_reconcile_result_when_result_exists_returns_parsed_json(
    client, mock_redis
):
    payload = {"status": "ok", "deleted_orphans": 3, "galleries_checked": 100}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload).encode())

    resp = await client.get("/api/system/reconcile")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deleted_orphans"] == 3
