"""
Integration tests for the queue admin router (/api/admin/queue/*).

Uses the `client` fixture (authenticated as admin user_id=1).
SAQ Queue is mocked via patch("core.queue.get_queue").

The router accesses core.queue.get_queue() and core.queue.enqueue();
core.queue.enqueue is already patched globally by the conftest.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from saq.job import TERMINAL_STATUSES, Status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_job(
    function="test_job",
    status="complete",
    key="job-123",
    **kwargs,
):
    """Build a mock SAQ Job object with all attributes the router accesses."""
    job = MagicMock()
    job.key = key
    job.function = function
    # Status must be a real Status enum so TERMINAL_STATUSES membership checks work
    job.status = Status(status) if isinstance(status, str) else status
    job.kwargs = kwargs.get("kwargs", {})
    job.result = kwargs.get("result", None)
    job.error = kwargs.get("error", None)
    job.queued = kwargs.get("queued", 1700000000000)
    job.started = kwargs.get("started", 1700000001000)
    job.completed = kwargs.get("completed", 1700000002000)
    job.progress = kwargs.get("progress", 0)
    job.attempts = kwargs.get("attempts", 1)
    job.meta = kwargs.get("meta", {})
    job.abort = AsyncMock()
    job.to_dict = MagicMock(
        return_value={"function": function, "status": status, "key": key}
    )
    return job


def _make_mock_queue(jobs=None, workers=None):
    """Build a mock SAQ Queue with controllable info/job/iter_jobs responses."""
    q = AsyncMock()

    # info() response — used by queue_overview (jobs=False) and list_jobs fast path
    async def _info(jobs=False, offset=0, limit=20, **kwargs):
        raw_jobs = []
        if jobs:
            for j in (locals().get("_jobs") or []):
                raw_jobs.append(j.to_dict())
        return {
            "name": "default",
            "queued": 3,
            "active": 1,
            "scheduled": 2,
            "workers": workers or {},
            "jobs": raw_jobs,
        }

    # Bind the job list into the closure properly
    _job_list = list(jobs or [])

    async def _info_bound(jobs=False, offset=0, limit=20, **kwargs):
        raw_jobs = []
        if jobs:
            for j in _job_list:
                raw_jobs.append(j.to_dict())
        return {
            "name": "default",
            "queued": 3,
            "active": 1,
            "scheduled": 2,
            "workers": workers or {},
            "jobs": raw_jobs,
        }

    q.info = AsyncMock(side_effect=_info_bound)

    # job() — returns single job by key; override per test
    q.job = AsyncMock(return_value=None)

    # iter_jobs() — async generator over job list, respects statuses filter
    async def _iter_jobs(statuses=None, **kwargs):
        for j in _job_list:
            if statuses is not None and j.status not in statuses:
                continue
            yield j

    q.iter_jobs = _iter_jobs

    # deserialize() — called with a dict, return a mock job for each
    def _deserialize(d):
        if isinstance(d, dict):
            return _make_mock_job(**d)
        return d

    q.deserialize = MagicMock(side_effect=_deserialize)

    return q


@pytest.fixture
def mock_queue():
    """Patch core.queue.get_queue to return an empty mock queue."""
    q = _make_mock_queue()
    with patch("core.queue.get_queue", return_value=q):
        yield q


# ---------------------------------------------------------------------------
# Tests — GET /api/admin/queue/ (overview)
# ---------------------------------------------------------------------------


async def test_overview_returns_queue_stats(client, mock_queue):
    resp = await client.get("/api/admin/queue/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "default"
    assert data["queued"] == 3
    assert data["active"] == 1
    assert data["scheduled"] == 2
    assert "workers" in data
    assert isinstance(data["workers"], list)


async def test_overview_with_workers(client):
    workers = {
        "worker-abc": {"stats": {"complete": 10, "failed": 1}},
        "worker-xyz": {"stats": {"complete": 5, "failed": 0}},
    }
    q = _make_mock_queue(workers=workers)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["workers"]) == 2
    worker_ids = {w["id"] for w in data["workers"]}
    assert "worker-abc" in worker_ids
    assert "worker-xyz" in worker_ids
    # Verify stats are passed through
    for w in data["workers"]:
        if w["id"] == "worker-abc":
            assert w["stats"] == {"complete": 10, "failed": 1}


async def test_overview_calls_info_with_jobs_false(client, mock_queue):
    """queue_overview must call info(jobs=False) to skip expensive job listing."""
    await client.get("/api/admin/queue/")

    mock_queue.info.assert_called_once()
    call_kwargs = mock_queue.info.call_args
    # jobs=False should be passed (either positional or as kwarg)
    assert call_kwargs.kwargs.get("jobs") is False or (
        call_kwargs.args and call_kwargs.args[0] is False
    )


# ---------------------------------------------------------------------------
# Tests — GET /api/admin/queue/jobs (list)
# ---------------------------------------------------------------------------


async def test_jobs_list_returns_jobs(client):
    jobs = [
        _make_mock_job(function="download_job", status="complete", key="job-001"),
        _make_mock_job(function="scan_job", status="failed", key="job-002"),
    ]
    q = _make_mock_queue(jobs=jobs)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs")

    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data
    assert isinstance(data["jobs"], list)


async def test_jobs_list_pagination(client):
    """offset and limit parameters are forwarded to q.info()."""
    q = _make_mock_queue()
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs?offset=10&limit=5")

    assert resp.status_code == 200
    q.info.assert_called_once()
    call_kwargs = q.info.call_args.kwargs
    assert call_kwargs.get("offset") == 10
    assert call_kwargs.get("limit") == 5


async def test_jobs_list_limit_too_large_returns_422(client, mock_queue):
    """limit > 100 should be rejected with 422."""
    resp = await client.get("/api/admin/queue/jobs?limit=101")
    assert resp.status_code == 422


async def test_jobs_filter_by_status(client):
    """?status=failed uses iter_jobs and filters by Status enum."""
    jobs = [
        _make_mock_job(function="scan_job", status="failed", key="job-001"),
        _make_mock_job(function="download_job", status="complete", key="job-002"),
        _make_mock_job(function="tag_job", status="failed", key="job-003"),
    ]
    q = _make_mock_queue(jobs=jobs)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs?status=failed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for job in data["jobs"]:
        assert job["status"] == "failed"


async def test_jobs_filter_by_function(client):
    """?function=download_job uses iter_jobs and filters by function name."""
    jobs = [
        _make_mock_job(function="download_job", status="complete", key="job-001"),
        _make_mock_job(function="scan_job", status="complete", key="job-002"),
        _make_mock_job(function="download_job", status="failed", key="job-003"),
    ]
    q = _make_mock_queue(jobs=jobs)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs?function=download_job")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for job in data["jobs"]:
        assert job["function"] == "download_job"


async def test_jobs_filter_invalid_status_returns_422(client, mock_queue):
    """An unrecognized status value returns 422."""
    resp = await client.get("/api/admin/queue/jobs?status=nonexistent")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests — GET /api/admin/queue/jobs/{job_key} (detail)
# ---------------------------------------------------------------------------


async def test_job_detail_found(client):
    job = _make_mock_job(function="download_job", status="complete", key="job-123")
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=job)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs/job-123")

    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "job-123"
    assert data["function"] == "download_job"
    assert data["status"] == "complete"
    assert "kwargs" in data
    assert "error" in data
    assert "attempts" in data


async def test_job_detail_not_found(client):
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=None)
    with patch("core.queue.get_queue", return_value=q):
        resp = await client.get("/api/admin/queue/jobs/no-such-key")

    assert resp.status_code == 404
    assert "no-such-key" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests — POST /api/admin/queue/jobs/{job_key}/retry
# ---------------------------------------------------------------------------


async def test_retry_failed_job_succeeds(client):
    """Retrying a failed job re-enqueues it and returns new_key."""
    failed_job = _make_mock_job(
        function="download_job",
        status="failed",
        key="job-failed",
        kwargs={"url": "https://example.com"},
    )
    new_job = _make_mock_job(function="download_job", status="queued", key="job-new")

    q = _make_mock_queue()
    q.job = AsyncMock(return_value=failed_job)

    mock_enqueue = AsyncMock(return_value=new_job)
    with patch("core.queue.get_queue", return_value=q):
        with patch("core.queue.enqueue", mock_enqueue):
            resp = await client.post("/api/admin/queue/jobs/job-failed/retry")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "retried"
    assert data["new_key"] == "job-new"
    mock_enqueue.assert_called_once_with("download_job", url="https://example.com")


async def test_retry_complete_job_succeeds(client):
    """Retrying a completed job is also valid (complete is in TERMINAL_STATUSES)."""
    complete_job = _make_mock_job(
        function="scan_job",
        status="complete",
        key="job-done",
        kwargs={},
    )
    new_job = _make_mock_job(function="scan_job", status="queued", key="job-new2")

    q = _make_mock_queue()
    q.job = AsyncMock(return_value=complete_job)

    mock_enqueue = AsyncMock(return_value=new_job)
    with patch("core.queue.get_queue", return_value=q):
        with patch("core.queue.enqueue", mock_enqueue):
            resp = await client.post("/api/admin/queue/jobs/job-done/retry")

    assert resp.status_code == 200
    assert resp.json()["status"] == "retried"


async def test_retry_active_job_returns_409(client):
    """Cannot retry an active job — not in a terminal state."""
    active_job = _make_mock_job(
        function="download_job",
        status="active",
        key="job-active",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=active_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-active/retry")

    assert resp.status_code == 409
    assert "terminal" in resp.json()["detail"].lower()


async def test_retry_queued_job_returns_409(client):
    """Cannot retry a queued job — not in a terminal state."""
    queued_job = _make_mock_job(
        function="download_job",
        status="queued",
        key="job-queued",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=queued_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-queued/retry")

    assert resp.status_code == 409


async def test_retry_nonexistent_job_returns_404(client):
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=None)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/no-job/retry")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — POST /api/admin/queue/jobs/{job_key}/abort
# ---------------------------------------------------------------------------


async def test_abort_active_job_succeeds(client):
    """Aborting an active job calls job.abort() and returns aborted status."""
    active_job = _make_mock_job(
        function="download_job",
        status="active",
        key="job-active",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=active_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-active/abort")

    assert resp.status_code == 200
    assert resp.json()["status"] == "aborted"
    active_job.abort.assert_called_once_with("aborted by admin")


async def test_abort_queued_job_succeeds(client):
    """Aborting a queued job (not yet terminal) should succeed."""
    queued_job = _make_mock_job(
        function="scan_job",
        status="queued",
        key="job-queued",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=queued_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-queued/abort")

    assert resp.status_code == 200
    queued_job.abort.assert_called_once_with("aborted by admin")


async def test_abort_completed_job_returns_409(client):
    """Cannot abort a job already in a terminal state."""
    complete_job = _make_mock_job(
        function="scan_job",
        status="complete",
        key="job-done",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=complete_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-done/abort")

    assert resp.status_code == 409
    assert "terminal" in resp.json()["detail"].lower()
    complete_job.abort.assert_not_called()


async def test_abort_failed_job_returns_409(client):
    """Cannot abort a failed job — already in terminal state."""
    failed_job = _make_mock_job(
        function="download_job",
        status="failed",
        key="job-failed",
    )
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=failed_job)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/job-failed/abort")

    assert resp.status_code == 409
    failed_job.abort.assert_not_called()


async def test_abort_nonexistent_job_returns_404(client):
    q = _make_mock_queue()
    q.job = AsyncMock(return_value=None)

    with patch("core.queue.get_queue", return_value=q):
        resp = await client.post("/api/admin/queue/jobs/no-job/abort")

    assert resp.status_code == 404
