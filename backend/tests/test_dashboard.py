"""
Tests for GET /api/download/dashboard and DownloadSemaphore event emission.

Covers:
- Dashboard requires admin role (member and viewer get 403)
- Admin access returns 200
- Response has expected shape (active_jobs, queued_jobs, site_stats, global, system)
- Running and queued jobs appear in the correct response sections
- global.total_running and global.total_queued reflect DB counts
- global.total_today counts only today's jobs, not yesterday's
- DownloadSemaphore.acquire() emits SEMAPHORE_CHANGED with action="acquire"
- DownloadSemaphore.release() emits SEMAPHORE_CHANGED with action="release"
- Dashboard returns timing data when present in a job's progress JSONB
"""

import json
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_job(
    db_session,
    url: str = "https://e-hentai.org/g/123/abc/",
    status: str = "queued",
    source: str = "ehentai",
    user_id: int | None = None,
    progress: dict | None = None,
    created_at: str | None = None,
) -> str:
    """Insert a download job via raw SQL (SQLite-compatible)."""
    job_id = str(uuid.uuid4())
    progress_json = json.dumps(progress or {})
    params: dict = {
        "id": job_id,
        "url": url,
        "source": source,
        "status": status,
        "progress": progress_json,
        "user_id": user_id,
    }
    if created_at:
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, source, status, progress, user_id, created_at) "
                "VALUES (:id, :url, :source, :status, :progress, :user_id, :created_at)"
            ),
            {**params, "created_at": created_at},
        )
    else:
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, source, status, progress, user_id) "
                "VALUES (:id, :url, :source, :status, :progress, :user_id)"
            ),
            params,
        )
    await db_session.commit()
    return job_id


# ---------------------------------------------------------------------------
# Role-scoped client fixtures (member and viewer)
# ---------------------------------------------------------------------------


_conftest = sys.modules.get("conftest") or sys.modules.get("tests.conftest")
assert _conftest is not None, "conftest module not found in sys.modules"
_app = _conftest._app
_fake_get_db = _conftest._fake_get_db


@pytest.fixture
async def admin_client(db_session, db_session_factory, mock_redis):
    """Admin-role client with all dashboard dependencies patched."""
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 1, "role": "admin"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth
    _app.state.arq = AsyncMock()
    _app.state.arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job"))

    patches = [
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.download.get_redis", return_value=mock_redis),
        patch("core.site_config.AsyncSessionLocal", db_session_factory),
        patch("core.site_config.get_redis", return_value=mock_redis),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def member_client(db_session, db_session_factory, mock_redis):
    """Member-role client."""
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 2, "role": "member"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth
    _app.state.arq = AsyncMock()
    _app.state.arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job"))

    patches = [
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def viewer_client(db_session, db_session_factory, mock_redis):
    """Viewer-role client."""
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 3, "role": "viewer"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth

    patches = [
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared mock helpers for the dashboard endpoint
# ---------------------------------------------------------------------------


def _make_dashboard_mocks(mock_redis):
    """Return patches needed by the dashboard endpoint's Redis/disk/adaptive calls."""
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.scan = AsyncMock(return_value=(0, []))
    mock_redis.zcard = AsyncMock(return_value=0)

    _default_adaptive = MagicMock(last_signal="ok", last_signal_at=None)
    return [
        patch("core.adaptive.adaptive_engine.get_state", new_callable=AsyncMock, return_value=_default_adaptive),
        patch("core.adaptive.adaptive_engine.get_states_batch", new_callable=AsyncMock, return_value={}),
        patch("core.site_config.site_config_service.get_all_download_params", new_callable=AsyncMock, return_value={}),
        patch("worker.helpers.check_disk_space", return_value=(True, 42.0)),
        patch("worker.constants.DISK_LOW_KEY", "disk:low"),
    ]


# ---------------------------------------------------------------------------
# Test: role-based access control
# ---------------------------------------------------------------------------


class TestDashboardAccessControl:
    """Dashboard endpoint enforces admin-only access."""

    async def test_dashboard_member_returns_403(self, member_client):
        """Member role must be denied access with HTTP 403."""
        resp = await member_client.get("/api/download/dashboard")
        assert resp.status_code == 403

    async def test_dashboard_viewer_returns_403(self, viewer_client):
        """Viewer role must be denied access with HTTP 403."""
        resp = await viewer_client.get("/api/download/dashboard")
        assert resp.status_code == 403

    async def test_dashboard_admin_returns_200(self, admin_client, mock_redis):
        """Admin role must receive HTTP 200."""
        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: response shape
# ---------------------------------------------------------------------------


class TestDashboardShape:
    """Dashboard response must contain all expected top-level keys."""

    async def test_dashboard_returns_expected_shape(self, admin_client, mock_redis):
        """Response must contain active_jobs, queued_jobs, site_stats, global, system."""
        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        assert resp.status_code == 200
        data = resp.json()

        assert "active_jobs" in data
        assert isinstance(data["active_jobs"], list)

        assert "queued_jobs" in data
        assert isinstance(data["queued_jobs"], list)

        assert "site_stats" in data
        assert isinstance(data["site_stats"], dict)

        assert "global" in data
        g = data["global"]
        assert "boost_mode" in g
        assert "total_running" in g
        assert "total_queued" in g
        assert "total_today" in g

        assert "system" in data
        s = data["system"]
        assert "disk_free_gb" in s
        assert "disk_ok" in s

    async def test_dashboard_global_boost_mode_is_bool(self, admin_client, mock_redis):
        """global.boost_mode must be a boolean value."""
        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert isinstance(data["global"]["boost_mode"], bool)

    async def test_dashboard_system_disk_ok_is_bool(self, admin_client, mock_redis):
        """system.disk_ok must be a boolean value."""
        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert isinstance(data["system"]["disk_ok"], bool)


# ---------------------------------------------------------------------------
# Test: running and queued jobs reflected in response
# ---------------------------------------------------------------------------


class TestDashboardJobLists:
    """Jobs inserted in DB must appear in the correct response sections."""

    async def test_dashboard_running_job_appears_in_active_jobs(self, admin_client, db_session, mock_redis):
        """A job with status='running' must appear in active_jobs."""
        job_id = await _insert_job(db_session, status="running", source="ehentai")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        active_ids = [j["id"] for j in data["active_jobs"]]
        assert job_id in active_ids

    async def test_dashboard_queued_job_appears_in_queued_jobs(self, admin_client, db_session, mock_redis):
        """A job with status='queued' must appear in queued_jobs."""
        job_id = await _insert_job(db_session, status="queued", source="ehentai")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        queued_ids = [j["id"] for j in data["queued_jobs"]]
        assert job_id in queued_ids

    async def test_dashboard_total_running_matches_db_count(self, admin_client, db_session, mock_redis):
        """global.total_running must equal the number of running jobs in DB."""
        await _insert_job(db_session, status="running", source="ehentai", url="https://e-hentai.org/g/1/aaa/")
        await _insert_job(db_session, status="running", source="ehentai", url="https://e-hentai.org/g/2/bbb/")
        await _insert_job(db_session, status="queued", source="ehentai", url="https://e-hentai.org/g/3/ccc/")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert data["global"]["total_running"] == 2

    async def test_dashboard_total_queued_matches_db_count(self, admin_client, db_session, mock_redis):
        """global.total_queued must equal the number of queued jobs in DB."""
        await _insert_job(db_session, status="queued", source="ehentai", url="https://e-hentai.org/g/1/aaa/")
        await _insert_job(db_session, status="queued", source="ehentai", url="https://e-hentai.org/g/2/bbb/")
        await _insert_job(db_session, status="running", source="ehentai", url="https://e-hentai.org/g/3/ccc/")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert data["global"]["total_queued"] == 2

    async def test_dashboard_running_job_not_in_queued_jobs(self, admin_client, db_session, mock_redis):
        """A running job must not appear in queued_jobs."""
        job_id = await _insert_job(db_session, status="running", source="ehentai")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        queued_ids = [j["id"] for j in data["queued_jobs"]]
        assert job_id not in queued_ids


# ---------------------------------------------------------------------------
# Test: total_today counts only today's jobs
# ---------------------------------------------------------------------------


class TestDashboardTotalToday:
    """total_today must count only jobs created since midnight UTC today."""

    async def test_dashboard_total_today_excludes_yesterday(self, admin_client, db_session, mock_redis):
        """A job created yesterday must not be counted in total_today."""
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        await _insert_job(
            db_session,
            status="done",
            source="ehentai",
            url="https://e-hentai.org/g/1/aaa/",
            created_at=yesterday,
        )

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert data["global"]["total_today"] == 0

    async def test_dashboard_total_today_counts_only_today(self, admin_client, db_session, mock_redis):
        """Only today's job should be counted; yesterday's job is excluded."""
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        today = datetime.now(UTC).isoformat()

        await _insert_job(
            db_session,
            status="done",
            source="ehentai",
            url="https://e-hentai.org/g/1/aaa/",
            created_at=yesterday,
        )
        await _insert_job(
            db_session,
            status="done",
            source="ehentai",
            url="https://e-hentai.org/g/2/bbb/",
            created_at=today,
        )

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert data["global"]["total_today"] == 1


# ---------------------------------------------------------------------------
# Test: dashboard cache bypass (fresh data on each call in tests)
# ---------------------------------------------------------------------------


class TestDashboardCacheBypass:
    """Ensure the dashboard returns fresh data when cache is absent."""

    async def test_dashboard_returns_fresh_data_when_cache_empty(self, admin_client, db_session, mock_redis):
        """With no cached snapshot, dashboard must query DB and return live data."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.scan = AsyncMock(return_value=(0, []))
        mock_redis.zcard = AsyncMock(return_value=0)

        await _insert_job(db_session, status="running", source="ehentai")

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        assert resp.status_code == 200
        assert len(resp.json()["active_jobs"]) >= 1


# ---------------------------------------------------------------------------
# Test: timing data in active job progress
# ---------------------------------------------------------------------------


class TestDashboardTimingData:
    """Dashboard preserves timing data stored in a job's progress JSONB."""

    async def test_dashboard_active_job_progress_includes_timing_when_present(
        self, admin_client, db_session, mock_redis
    ):
        """When a running job has timing data in progress, active_jobs exposes it."""
        timing_payload = {
            "semaphore_wait_ms": 120,
            "avg_page_ms": 850,
            "idle_ms": 200,
            "elapsed_ms": 5000,
        }
        await _insert_job(
            db_session,
            status="running",
            source="ehentai",
            progress={"percent": 50, "downloaded": 10, "total": 20, "timing": timing_payload},
        )

        with ExitStack() as stack:
            for p in _make_dashboard_mocks(mock_redis):
                stack.enter_context(p)
            resp = await admin_client.get("/api/download/dashboard")

        data = resp.json()
        assert len(data["active_jobs"]) >= 1
        job = data["active_jobs"][0]
        assert "progress" in job
        assert "timing" in job["progress"]
        assert job["progress"]["timing"]["semaphore_wait_ms"] == 120
        assert job["progress"]["timing"]["avg_page_ms"] == 850


# ---------------------------------------------------------------------------
# Test: DownloadSemaphore event emission
# ---------------------------------------------------------------------------


class TestSemaphoreEventEmission:
    """DownloadSemaphore.acquire() and .release() must emit SEMAPHORE_CHANGED events."""

    async def test_semaphore_acquire_emits_semaphore_changed_event(self, mock_redis):
        """acquire() must call emit_safe with EventType.SEMAPHORE_CHANGED and action='acquire'."""
        from core.events import EventType
        from core.redis_client import DownloadSemaphore

        # eval returns 1 (slot acquired immediately)
        mock_redis.eval = AsyncMock(return_value=1)

        sem = DownloadSemaphore("ehentai")
        job_id = str(uuid.uuid4())

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.events.emit_safe", new_callable=AsyncMock) as mock_emit,
        ):
            await sem.acquire(job_id)

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        # First positional arg is the event type
        assert call_kwargs.args[0] == EventType.SEMAPHORE_CHANGED
        assert call_kwargs.kwargs.get("action") == "acquire"
        assert call_kwargs.kwargs.get("job_id") == job_id

    async def test_semaphore_release_emits_semaphore_changed_event(self, mock_redis):
        """release() must call emit_safe with EventType.SEMAPHORE_CHANGED and action='release'."""
        from core.events import EventType
        from core.redis_client import DownloadSemaphore

        mock_redis.zrem = AsyncMock(return_value=1)

        sem = DownloadSemaphore("ehentai")
        job_id = str(uuid.uuid4())

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.events.emit_safe", new_callable=AsyncMock) as mock_emit,
        ):
            await sem.release(job_id)

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        assert call_kwargs.args[0] == EventType.SEMAPHORE_CHANGED
        assert call_kwargs.kwargs.get("action") == "release"
        assert call_kwargs.kwargs.get("job_id") == job_id

    async def test_semaphore_acquire_polls_until_slot_available(self, mock_redis):
        """acquire() must retry when Redis eval returns 0 (no slot) then succeed on second call."""
        from core.redis_client import DownloadSemaphore

        # First call returns 0 (busy), second returns 1 (acquired)
        mock_redis.eval = AsyncMock(side_effect=[0, 1])

        sem = DownloadSemaphore("ehentai", acquire_timeout=5)
        job_id = str(uuid.uuid4())

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            wait_secs = await sem.acquire(job_id)

        assert mock_redis.eval.call_count == 2
        assert isinstance(wait_secs, float)

    async def test_semaphore_acquire_raises_timeout_when_no_slot(self, mock_redis):
        """acquire() must raise TimeoutError when the semaphore stays full past the deadline."""
        from core.redis_client import DownloadSemaphore

        # Always return 0 (slot never available)
        mock_redis.eval = AsyncMock(return_value=0)

        sem = DownloadSemaphore("ehentai", acquire_timeout=0)
        job_id = str(uuid.uuid4())

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            with pytest.raises(TimeoutError):
                await sem.acquire(job_id)
