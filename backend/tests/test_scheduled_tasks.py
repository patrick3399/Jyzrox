"""
Integration tests for the scheduled tasks router (/api/scheduled-tasks/*).

Uses the `client` fixture (authenticated as admin user_id=1).
Redis calls are handled by the mock_redis fixture already patched in the
client fixture via core.redis_client.get_redis.

All tasks are defined statically in TASK_DEFS inside the router — no DB
inserts are required for these tests.
"""

from unittest.mock import AsyncMock

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session):
    await db_session.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'hash', 'admin')")
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


async def test_scheduled_tasks_list_each_task_has_expected_fields(client, mock_redis):
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
        assert "next_run" in task


async def test_scheduled_tasks_list_contains_known_task_ids(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    task_ids = {t["id"] for t in resp.json()["tasks"]}
    # These are defined in TASK_DEFS in the router
    assert "library_scan" in task_ids
    assert "reconciliation" in task_ids
    assert "check_subscriptions" in task_ids
    assert "database_backup" in task_ids


async def test_scheduled_tasks_library_scan_has_user_facing_name_and_next_run(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    library_scan = next(task for task in resp.json()["tasks"] if task["id"] == "library_scan")
    assert library_scan["name"] == "External Folder Scan"
    assert "external folders" in library_scan["description"]
    assert library_scan["next_run"] is not None


async def test_scheduled_tasks_disabled_task_has_null_next_run(client, mock_redis):
    async def get_value(key):
        if key == "cron:library_scan:enabled":
            return b"0"
        return None

    mock_redis.get = AsyncMock(side_effect=get_value)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    library_scan = next(task for task in resp.json()["tasks"] if task["id"] == "library_scan")
    assert library_scan["enabled"] is False
    assert library_scan["next_run"] is None


async def test_scheduled_tasks_stale_running_status_is_reported(client, mock_redis):
    async def get_value(key):
        if key == "cron:library_scan:last_status":
            return b"running"
        if key == "cron:library_scan:last_run":
            return b"2026-05-01T04:57:08.564396+00:00"
        return None

    mock_redis.get = AsyncMock(side_effect=get_value)
    mock_redis.exists = AsyncMock(return_value=0)

    resp = await client.get("/api/scheduled-tasks/")

    assert resp.status_code == 200
    library_scan = next(task for task in resp.json()["tasks"] if task["id"] == "library_scan")
    assert library_scan["last_status"] == "stale"


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
    mock_redis.set.assert_called_with("cron:reconciliation:cron_expr", "0 4 * * 0")


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

    app.state.enqueue.assert_called_once()
    call_args = app.state.enqueue.call_args
    assert call_args.args[0] == "scheduled_scan_job"
    assert call_args.kwargs["force"] is True
    assert call_args.kwargs["_timeout"] == 7200
    assert call_args.kwargs["_job_id"].startswith("manual:library_scan:")


async def test_scheduled_tasks_run_reconciliation_enqueues_force(client):
    resp = await client.post("/api/scheduled-tasks/reconciliation/run")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["task_id"] == "reconciliation"
    assert data["job"] == "reconciliation_job"

    from main import app

    app.state.enqueue.assert_called_once()
    call_args = app.state.enqueue.call_args
    assert call_args.args[0] == "reconciliation_job"
    assert call_args.kwargs["force"] is True
    assert call_args.kwargs["_timeout"] == 3600
    assert call_args.kwargs["_job_id"].startswith("manual:reconciliation:")


async def test_scheduled_tasks_run_database_backup_enqueues_force(client):
    resp = await client.post("/api/scheduled-tasks/database_backup/run")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["task_id"] == "database_backup"
    assert data["job"] == "database_backup_job"

    from main import app

    app.state.enqueue.assert_called_once()
    call_args = app.state.enqueue.call_args
    assert call_args.args[0] == "database_backup_job"
    assert call_args.kwargs["force"] is True
    assert call_args.kwargs["_timeout"] == 3600
    assert call_args.kwargs["_job_id"].startswith("manual:database_backup:")


async def test_scheduled_tasks_run_deduplicates_manual_clicks(client, mock_redis):
    mock_redis.set = AsyncMock(return_value=False)

    resp = await client.post("/api/scheduled-tasks/library_scan/run")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_queued"
    assert data["task_id"] == "library_scan"
    assert data["job"] == "scheduled_scan_job"

    from main import app

    app.state.enqueue.assert_not_called()


async def test_scheduled_tasks_run_unknown_task_returns_404(client):
    resp = await client.post("/api/scheduled-tasks/nonexistent_task_id/run")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression — catalog consistency (edge-case audit #24–#27)
# ---------------------------------------------------------------------------


def test_catalog_configurable_task_ids_match_router_task_defs():
    """CONFIGURABLE_TASK_DEFS must equal the set the router exposes — no silent
    divergence between the catalog and what the UI can reach."""
    from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
    from routers.scheduled_tasks import CONFIGURABLE_TASK_DEFS as router_defs

    assert set(CONFIGURABLE_TASK_DEFS.keys()) == set(router_defs.keys())


def test_catalog_check_subscriptions_job_name_matches_cron_should_run_task_id():
    """check_followed_artists calls _cron_should_run('check_subscriptions', ...).
    The catalog must map task_id='check_subscriptions' → job_name='check_followed_artists'
    so that the Redis gate key and the UI task ID stay in sync. (#24)"""
    from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS

    defn = CONFIGURABLE_TASK_DEFS["check_subscriptions"]
    assert defn.job_name == "check_followed_artists"


def test_catalog_required_jobs_are_registered_as_cron_jobs():
    """All catalog entries with CronJob requirements must appear in the list
    built by _build_cron_jobs(). Covers: #24 (check_followed_artists added),
    #25 (dedup tiers added), #27 (background-only jobs present)."""
    from worker import _build_cron_jobs

    cron_jobs = {job.function.__name__: job for job in _build_cron_jobs()}
    required = {
        # #24 — subscription schedule was missing
        "check_followed_artists",
        # #25 — dedup had no CronJob entries
        "dedup_tier1_job", "dedup_tier2_job", "dedup_tier3_job",
        # #27 — background jobs not previously catalogued
        "trash_gc_job", "log_cleanup_job", "disk_monitor_job",
        "adaptive_persist_job", "rate_limit_schedule_job",
    }
    missing = required - cron_jobs.keys()
    assert not missing, f"Missing from CronJob list: {missing}"


def test_catalog_ehtag_sync_cron_is_consistent_between_catalog_and_cron_job():
    """ehtag_sync default_cron in catalog must match the CronJob schedule so
    the gate interval and SAQ wake-up are aligned. (#26)"""
    from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
    from worker import _build_cron_jobs

    expected_cron = CONFIGURABLE_TASK_DEFS["ehtag_sync"].default_cron
    cron_jobs = {job.function.__name__: job for job in _build_cron_jobs()}
    assert "ehtag_sync_job" in cron_jobs
    assert cron_jobs["ehtag_sync_job"].cron == expected_cron


def test_catalog_all_configurable_tasks_have_valid_default_cron():
    """All configurable tasks must have valid cron expressions so the UI
    next_run calculation never raises."""
    from croniter import croniter

    from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS

    for task_id, defn in CONFIGURABLE_TASK_DEFS.items():
        assert croniter.is_valid(defn.default_cron), (
            f"{task_id} has invalid default_cron: {defn.default_cron!r}"
        )
