"""
Integration tests for the scheduled tasks router (/api/scheduled-tasks/*).

Uses the `client` fixture (authenticated as admin user_id=1).
Redis calls are handled by the mock_redis fixture already patched in the
client fixture via core.redis_client.get_redis.

All tasks are defined statically in TASK_DEFS inside the router — no DB
inserts are required for these tests.
"""

from unittest.mock import AsyncMock

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
# Tests — list tasks
# ---------------------------------------------------------------------------


async def test_scheduled_tasks_list_returns_task_list(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) > 0


async def test_scheduled_tasks_list_each_task_has_expected_fields(
    client, mock_redis
):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    for task in resp.json()["tasks"]:
        assert "id" in task
        assert "name" in task
        assert "enabled" in task
        assert "cron_expr" in task
        assert "description" in task
        assert "default_cron" in task


async def test_scheduled_tasks_list_contains_known_task_ids(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    task_ids = {t["id"] for t in resp.json()["tasks"]}
    # These are defined in TASK_DEFS in the router
    assert "library_scan" in task_ids
    assert "reconciliation" in task_ids
    assert "check_subscriptions" in task_ids


# ---------------------------------------------------------------------------
# Tests — update task
# ---------------------------------------------------------------------------


async def test_scheduled_tasks_update_enabled_false_returns_200(client, mock_redis):
    mock_redis.set = AsyncMock(return_value=True)

    resp = await client.patch(
        "/api/scheduled-tasks/library_scan",
        json={"enabled": False},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["task_id"] == "library_scan"
    mock_redis.set.assert_called_with("cron:library_scan:enabled", "0")


async def test_scheduled_tasks_update_cron_expr_returns_200(client, mock_redis):
    mock_redis.set = AsyncMock(return_value=True)

    resp = await client.patch(
        "/api/scheduled-tasks/reconciliation",
        json={"cron_expr": "0 4 * * 0"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["task_id"] == "reconciliation"
    mock_redis.set.assert_called_with(
        "cron:reconciliation:cron_expr", "0 4 * * 0"
    )


async def test_scheduled_tasks_update_invalid_cron_returns_400(client, mock_redis):
    resp = await client.patch(
        "/api/scheduled-tasks/library_scan",
        json={"cron_expr": "not_a_cron"},
    )
    assert resp.status_code == 400


async def test_scheduled_tasks_update_unknown_task_returns_404(client, mock_redis):
    resp = await client.patch(
        "/api/scheduled-tasks/nonexistent_task_id",
        json={"enabled": True},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — run task
# ---------------------------------------------------------------------------


async def test_scheduled_tasks_run_enqueues_job(client):
    resp = await client.post("/api/scheduled-tasks/library_scan/run")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["task_id"] == "library_scan"
    assert data["job"] == "scheduled_scan_job"

    from main import app
    app.state.arq.enqueue_job.assert_called_with(
        "scheduled_scan_job", _job_id="manual:library_scan"
    )


async def test_scheduled_tasks_run_unknown_task_returns_404(client):
    resp = await client.post("/api/scheduled-tasks/nonexistent_task_id/run")
    assert resp.status_code == 404
