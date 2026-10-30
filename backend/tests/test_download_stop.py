"""POST /jobs/{id}/stop, cancel delegation, retry guard, and the keep path's cancel guard."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._download_stop_support import add_job

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


@pytest.fixture
def enq():
    mock = AsyncMock()
    with patch("core.queue.enqueue", mock):
        yield mock


@pytest.fixture
def redis_patched(mock_redis):
    with (
        patch("routers.download.get_redis", return_value=mock_redis),
        patch("services.download_stop.get_redis", return_value=mock_redis),
    ):
        yield mock_redis


async def test_stop_running_job_sets_intent_and_keeps_running_status(client, db_session, enq, redis_patched):
    job = await add_job(db_session, status="running", admission_token=uuid.uuid4())

    resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 200
    assert resp.json() == {"status": "running", "stopping": True}
    await db_session.refresh(job)
    assert job.status == "running"  # the worker ends it; guards keep seeing an active job
    assert job.stop_requested_at is not None
    redis_patched.setex.assert_awaited_once_with(f"download:cancel:{job.id}", 3600, "stop")
    enq.assert_not_awaited()  # a live execution runs its own keep path


async def test_stop_without_live_execution_enqueues_finalize_before_commit(client, db_session, enq, redis_patched):
    """BE-T19: no admission token -> finalize_stopped_job is enqueued first, the intent committed after."""
    job = await add_job(db_session, status="queued", admission_token=None)
    events: list[str] = []
    real_commit = db_session.commit

    async def _commit():
        events.append("commit")
        await real_commit()

    async def _enqueue(*args, **kwargs):
        events.append("enqueue")

    enq.side_effect = _enqueue

    with patch.object(db_session, "commit", _commit):
        resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "stopping": True}
    assert events == ["enqueue", "commit"]  # the enqueue happens while the intent is still uncommitted
    enq.assert_awaited_once()
    assert enq.await_args.args == ("finalize_stopped_job",)
    kwargs = enq.await_args.kwargs
    assert kwargs["db_job_id"] == str(job.id)
    assert kwargs["_job_id"].startswith(f"stop:{job.id}:")
    await db_session.refresh(job)
    assert job.stop_requested_at is not None


async def test_stop_enqueue_failure_commits_no_intent(client, db_session, enq, redis_patched):
    """A failed enqueue must not leave a committed intent that nobody will ever serve."""
    job = await add_job(db_session, status="paused", admission_token=None)
    enq.side_effect = RuntimeError("queue down")

    resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 500
    await db_session.refresh(job)
    assert job.stop_requested_at is None
    redis_patched.setex.assert_not_awaited()


@pytest.mark.parametrize("status", ["done", "failed", "cancelled", "partial"])
async def test_stop_terminal_job_returns_409(client, db_session, enq, redis_patched, status):
    job = await add_job(db_session, status=status)

    resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 409
    assert resp.json()["detail"] == f"Cannot stop: status={status}"
    await db_session.refresh(job)
    assert job.stop_requested_at is None
    redis_patched.setex.assert_not_awaited()
    enq.assert_not_awaited()


async def test_stop_is_idempotent_and_does_not_enqueue_a_second_finalize(client, db_session, enq, redis_patched):
    job = await add_job(db_session, status="paused", admission_token=None, stop_requested_at=NOW)

    resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 200
    assert resp.json() == {"status": "paused", "stopping": True}
    enq.assert_not_awaited()


async def test_stop_unknown_job_returns_404(client, enq, redis_patched):
    resp = await client.post(f"/api/download/jobs/{uuid.uuid4()}/stop")
    assert resp.status_code == 404


async def test_stop_other_users_job_returns_403_for_a_member(make_client, db_session, enq, redis_patched):
    job = await add_job(db_session, status="running", user_id=99, admission_token=uuid.uuid4())

    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 403
    await db_session.refresh(job)
    assert job.stop_requested_at is None


async def test_cancel_repair_job_acts_as_stop(client, db_session, enq, redis_patched):
    """DELETE on a repair job keeps the repaired files: it records a stop, it does not discard."""
    job = await add_job(db_session, status="running", mode="repair", admission_token=uuid.uuid4())

    resp = await client.delete(f"/api/download/jobs/{job.id}")

    assert resp.status_code == 200
    assert resp.json() == {"status": "running", "stopping": True}
    await db_session.refresh(job)
    assert job.status == "running"
    assert job.stop_requested_at is not None
    redis_patched.setex.assert_awaited_once_with(f"download:cancel:{job.id}", 3600, "stop")


async def test_cancel_legacy_force_full_scan_job_acts_as_stop(client, db_session, enq, redis_patched):
    """A repair queued before the mode column existed carries only options.force_full_scan."""
    job = await add_job(
        db_session,
        status="running",
        mode="download",
        options={"force_full_scan": True},
        admission_token=uuid.uuid4(),
    )

    resp = await client.delete(f"/api/download/jobs/{job.id}")

    assert resp.json() == {"status": "running", "stopping": True}
    await db_session.refresh(job)
    assert job.stop_requested_at is not None


@pytest.mark.parametrize("mode", ["download", "subscription_initial", "subscription_incremental"])
async def test_cancel_non_repair_job_still_discards(client, db_session, enq, redis_patched, mode):
    job = await add_job(db_session, status="running", mode=mode, admission_token=uuid.uuid4())

    resp = await client.delete(f"/api/download/jobs/{job.id}")

    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled"}
    await db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.stop_requested_at is None


async def test_cancel_after_stop_request_marks_the_job_cancelled(client, db_session, enq, redis_patched):
    """A stop followed by a discard: the DB row ends cancelled, which the keep path then honours."""
    job = await add_job(
        db_session, status="running", mode="download", admission_token=uuid.uuid4(), stop_requested_at=NOW
    )

    resp = await client.delete(f"/api/download/jobs/{job.id}")

    assert resp.json() == {"status": "cancelled"}
    await db_session.refresh(job)
    assert job.status == "cancelled"


async def test_cancel_after_stop_discards(db_session, db_session_factory):
    """The worker keep path re-reads the DB: a `cancelled` row wins over the stop (HR-005, A2)."""
    from worker.download import _finish_stopped

    job = await add_job(
        db_session, status="cancelled", mode="subscription_incremental", subscription_id=None, stop_requested_at=NOW
    )
    importer = MagicMock()
    importer.gallery_id = 5
    importer.cleanup = AsyncMock()
    importer.finalize_kept = AsyncMock()
    importer.has_processed = MagicMock(return_value=True)
    set_status = AsyncMock()
    set_sub = AsyncMock()

    with (
        patch("core.database.AsyncSessionLocal", db_session_factory),
        patch("services.download_stop.AsyncSessionLocal", db_session_factory),
        patch("worker.download._set_job_status", set_status),
        patch("worker.download._set_subscription_result", set_sub),
        patch("worker.download._import_staged_leftovers", AsyncMock(return_value=0)),
    ):
        result = await _finish_stopped(
            importer=importer,
            target_dir=MagicMock(),
            url=job.url,
            plugin=MagicMock(),
            on_file=AsyncMock(),
            db_job_id=str(job.id),
            mode="subscription_incremental",
            started_at=NOW,
            boundary=NOW,
            credentials=None,
            credential_accounts=None,
            result=None,
        )

    assert result == {"status": "cancelled"}
    importer.cleanup.assert_awaited_once()
    importer.finalize_kept.assert_not_awaited()
    set_status.assert_not_awaited()  # the row already says cancelled; nothing rewrites it
    set_sub.assert_awaited_once_with(str(job.id), "cancelled")


async def test_retry_stopped_job_rejected(client, db_session, enq, redis_patched):
    """A stopped job is ended on purpose; replaying it would fetch the history the user gave up."""
    job = await add_job(db_session, status="failed", stop_requested_at=NOW, retry_count=0)

    resp = await client.post(f"/api/download/jobs/{job.id}/retry")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Cannot retry a stopped job"
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.retry_count == 0
    enq.assert_not_awaited()


async def test_retry_job_without_stop_intent_is_still_allowed(client, db_session, enq, redis_patched):
    job = await add_job(db_session, status="failed", retry_count=0)

    resp = await client.post(f"/api/download/jobs/{job.id}/retry")

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


async def test_stop_with_stale_snapshot_of_finished_job_returns_409(
    client, db_session, db_session_factory, enq, redis_patched
):
    """The decision is made on the DB row: an ORM snapshot that still says `running` must not record a stop."""
    from sqlalchemy import select, update

    from db.models import DownloadJob

    job = await add_job(db_session, status="running", admission_token=uuid.uuid4())
    async with db_session_factory() as other:  # the worker finishes the job behind the request's back
        await other.execute(update(DownloadJob).where(DownloadJob.id == job.id).values(status="done"))
        await other.commit()
    assert job.status == "running"  # the request's session still holds the stale snapshot

    resp = await client.post(f"/api/download/jobs/{job.id}/stop")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Cannot stop: status=done"
    async with db_session_factory() as check:
        row = (await check.execute(select(DownloadJob.status, DownloadJob.stop_requested_at))).one()
    assert row.status == "done" and row.stop_requested_at is None
    redis_patched.setex.assert_not_awaited()
    enq.assert_not_awaited()


async def test_cancel_with_stale_snapshot_does_not_overwrite_a_finished_job(
    client, db_session, db_session_factory, enq, redis_patched
):
    """The worker (or a stop's keep path) ended the job after the request loaded it: cancel must not turn a
    kept, `done` run into `cancelled`."""
    from sqlalchemy import select, update

    from db.models import DownloadJob

    job = await add_job(db_session, status="running", admission_token=uuid.uuid4(), stop_requested_at=NOW)
    async with db_session_factory() as other:
        await other.execute(update(DownloadJob).where(DownloadJob.id == job.id).values(status="done"))
        await other.commit()
    assert job.status == "running"  # stale snapshot

    resp = await client.delete(f"/api/download/jobs/{job.id}")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot cancel: status=done"
    async with db_session_factory() as check:
        assert (await check.execute(select(DownloadJob.status))).scalar_one() == "done"
    redis_patched.setex.assert_not_awaited()


async def test_cancel_while_the_keep_path_finalizes_is_refused_and_the_job_stays_done(
    client, db_session, db_session_factory, enq, redis_patched
):
    """Stop, then cancel while the worker is keeping the gallery. The keep path claimed the job first, so the
    cancel is refused: the job must not end `cancelled` with a kept gallery (or `done` after a cancel)."""
    from sqlalchemy import select

    from db.models import DownloadJob
    from worker.download import _finish_stopped

    job = await add_job(db_session, status="running", admission_token=uuid.uuid4(), stop_requested_at=NOW)
    cancel_codes: list[int] = []

    async def _finalize_kept(*_args, **_kwargs):
        cancel_codes.append((await client.delete(f"/api/download/jobs/{job.id}")).status_code)
        return 5

    importer = MagicMock()
    importer.gallery_id = 5
    importer.skipped_trashed = False
    importer.title = None
    importer.import_failures = ()
    importer.import_success_count = 1
    importer.skipped_duplicate_count = importer.skipped_excluded_count = importer.skipped_invalid_count = 0
    importer.cleanup = AsyncMock()
    importer.finalize_kept = AsyncMock(side_effect=_finalize_kept)

    with (
        patch("core.database.AsyncSessionLocal", db_session_factory),
        patch("services.download_stop.AsyncSessionLocal", db_session_factory),
        patch("worker.helpers.AsyncSessionLocal", db_session_factory),
        patch("worker.download._set_subscription_result", AsyncMock()),
        patch("worker.download._import_staged_leftovers", AsyncMock(return_value=0)),
        patch("worker.download._writeback_cookies", AsyncMock()),
        patch("worker.download.emit_safe", AsyncMock()),
    ):
        result = await _finish_stopped(
            importer=importer,
            target_dir=MagicMock(),
            url=job.url,
            plugin=MagicMock(),
            on_file=AsyncMock(),
            db_job_id=str(job.id),
            mode="download",
            started_at=NOW,
            boundary=NOW,
            credentials=None,
            credential_accounts=None,
            result=None,
        )

    assert cancel_codes == [400]
    assert result["outcome"] == "stopped"
    importer.cleanup.assert_not_awaited()
    async with db_session_factory() as check:
        row = (await check.execute(select(DownloadJob.status, DownloadJob.progress))).one()
    assert row.status == "done" and row.progress["outcome"] == "stopped"


# ── read_stop_intent: a failed lookup falls back to the Redis flag ───────


def _failing_sessions():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(side_effect=RuntimeError("connection reset"))
    session.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=session)


@pytest.mark.parametrize(
    ("flag", "expected"),
    [(b"stop", "stop"), ("stop", "stop"), (b"1", "cancel"), (None, None)],
)
async def test_read_stop_intent_db_error_falls_back_to_the_flag_value(flag, expected):
    from services.download_stop import read_stop_intent

    sessions = _failing_sessions()
    redis = MagicMock(get=AsyncMock(return_value=flag))
    with (
        patch("services.download_stop.AsyncSessionLocal", sessions),
        patch("services.download_stop.get_redis", MagicMock(return_value=redis)),
        patch("services.download_stop._INTENT_RETRY_DELAY_S", 0, create=True),
    ):
        assert await read_stop_intent("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d") == expected
    assert sessions.call_count == 2  # retried once before trusting the flag


async def test_read_stop_intent_db_and_redis_errors_report_no_intent():
    from services.download_stop import read_stop_intent

    redis = MagicMock(get=AsyncMock(side_effect=RuntimeError("redis down")))
    with (
        patch("services.download_stop.AsyncSessionLocal", _failing_sessions()),
        patch("services.download_stop.get_redis", MagicMock(return_value=redis)),
        patch("services.download_stop._INTENT_RETRY_DELAY_S", 0, create=True),
    ):
        assert await read_stop_intent("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d") is None
