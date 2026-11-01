"""A stop is a durable intent: restart recovery and the retry cron must serve it, never re-run or fail it away."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._download_stop_support import add_job, utc
from tests.test_worker_recovery import _make_job, _make_redis, _make_session, _run_startup

STOP_AT = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


def _stop_job(status="running", stop=True):
    job = _make_job("job-1", status=status)
    job.stop_requested_at = STOP_AT if stop else None
    job.admission_token = "stale-token"
    return job


async def _startup(job, *, running=None, paused=None, queued=None, strategy_running=None):
    redis = _make_redis(strategy_running=strategy_running)
    session = _make_session(
        running_jobs=[job] if running else [], paused_jobs=[job] if paused else [], queued_jobs=[job] if queued else []
    )
    finalize = AsyncMock()
    with (
        patch("worker.enqueue_finalize_stopped_job", finalize),
        patch("worker.release_dead_collection_lock", AsyncMock()),
    ):
        mocks = await _run_startup(redis, session)
    return mocks, finalize, redis


@pytest.mark.parametrize("strategy", [None, "auto_retry", "mark_failed"])
async def test_startup_recovery_finalizes_stop_requested_running_job_instead_of_retry(strategy):
    job = _stop_job("running")

    mocks, finalize, _ = await _startup(job, running=True, strategy_running=strategy)

    finalize.assert_awaited_once_with("job-1")
    mocks["enqueue"].assert_not_awaited()  # not re-run: that would download again what the user kept
    assert job.retry_count == 0
    assert job.status == "running"  # not failed either: finalize_stopped_job ends it
    assert job.admission_token is None  # the dead execution's fence is still cleared


async def test_startup_recovery_without_stop_intent_still_retries_running_job():
    """Control: the same job without an intent keeps the normal auto_retry recovery."""
    job = _stop_job("running", stop=False)

    mocks, finalize, _ = await _startup(job, running=True)

    finalize.assert_not_awaited()
    mocks["enqueue"].assert_awaited_once()
    assert job.retry_count == 1


async def test_startup_recovery_finalizes_stop_requested_paused_job_and_clears_pause_flag():
    job = _stop_job("paused")

    mocks, finalize, redis = await _startup(job, paused=True)

    finalize.assert_awaited_once_with("job-1")
    mocks["enqueue"].assert_not_awaited()
    redis.delete.assert_any_await("download:pause:job-1")


async def test_startup_recovery_finalizes_stop_requested_queued_job():
    job = _stop_job("queued")

    mocks, finalize, _ = await _startup(job, queued=True)

    finalize.assert_awaited_once_with("job-1")
    mocks["enqueue"].assert_not_awaited()


async def test_startup_recovery_falls_back_to_normal_policy_when_finalize_enqueue_fails():
    """The re-run sees the intent before it starts and takes the keep path without downloading."""
    from worker import _finish_stop_requested

    job = _stop_job("running")
    with (
        patch("worker.enqueue_finalize_stopped_job", AsyncMock(side_effect=RuntimeError("queue down"))),
        patch("worker.release_dead_collection_lock", AsyncMock()),
    ):
        assert await _finish_stop_requested(MagicMock(), job) is False


# ── retry cron (real SQLite rows) ───────────────────────────────────────


@pytest.fixture
def retry_env(db_session_factory):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    ns = MagicMock()
    ns.ctx = {"redis": redis}
    ns.retry_enqueue = AsyncMock()
    ns.finalize = AsyncMock()
    with (
        patch("worker.retry._cron_should_run", AsyncMock(return_value=True)),
        patch("worker.retry._cron_record", AsyncMock()),
        patch("worker.retry.AsyncSessionLocal", db_session_factory),
        patch("worker.retry.enqueue_download_job", ns.retry_enqueue),
        patch("worker.retry.enqueue_finalize_stopped_job", ns.finalize),
        patch("worker.retry.resolve_admission_key", AsyncMock(return_value="key")),
        patch("worker.retry.next_admission_ticket", AsyncMock(return_value=1)),
        patch("core.events.emit_safe", AsyncMock()),
    ):
        yield ns


async def test_auto_retry_skips_stop_requested_jobs(db_session, retry_env):
    """A stopped job ended by the user's choice; re-running it would fetch again what they chose to keep."""
    from worker.retry import retry_failed_downloads_job

    stopped = await add_job(db_session, status="failed", stop_requested_at=utc(2026, 10, 30, 10, 0), retry_count=0)
    normal = await add_job(db_session, status="failed", retry_count=0, url="https://e-hentai.org/g/9/abcdef9999/")

    result = await retry_failed_downloads_job(retry_env.ctx)

    assert result["retried"] == 1
    retry_env.retry_enqueue.assert_awaited_once()
    assert retry_env.retry_enqueue.await_args.args[0].id == normal.id
    await db_session.refresh(stopped)
    assert (stopped.status, stopped.retry_count) == ("failed", 0)


async def test_stale_reaper_hands_stop_requested_job_to_finalize_instead_of_failing_it(db_session, retry_env):
    from worker.retry import retry_failed_downloads_job

    old = datetime.now(UTC) - timedelta(hours=3)
    job = await add_job(
        db_session,
        status="running",
        admission_token=None,
        created_at=old,
        stop_requested_at=utc(2026, 10, 30, 10, 0),
        progress={"last_update_at": old.isoformat()},
    )

    await retry_failed_downloads_job(retry_env.ctx)

    retry_env.finalize.assert_awaited_once_with(job.id)
    await db_session.refresh(job)
    assert job.status == "running"  # not marked failed: that would drop the intent
    assert job.error is None


async def test_stale_reaper_without_stop_intent_still_fails_a_zombie_job(db_session, retry_env):
    """Control for the reaper test above."""
    from worker.retry import retry_failed_downloads_job

    old = datetime.now(UTC) - timedelta(hours=3)
    job = await add_job(
        db_session,
        status="running",
        admission_token=None,
        created_at=old,
        progress={"last_update_at": old.isoformat()},
    )

    await retry_failed_downloads_job(retry_env.ctx)

    retry_env.finalize.assert_not_awaited()
    await db_session.refresh(job)
    assert job.status != "running"


# ── startup: galleries left on `downloading` by a job that already ended ─


async def test_startup_settles_downloading_gallery_whose_stopped_job_is_already_done(db_session, db_session_factory):
    """A worker killed after the stop claim leaves the job `done` and its gallery `downloading`. Recovery only
    looks at `running` jobs, so the sweep must settle every `downloading` gallery no active job owns."""
    from sqlalchemy import select

    from db.models import Gallery, Image
    from tests._download_stop_support import add_gallery
    from worker import _settle_orphan_downloading_galleries

    kept = await add_gallery(db_session, source_id="1", download_status="downloading")
    empty = await add_gallery(db_session, source_id="2", download_status="downloading")
    active = await add_gallery(db_session, source_id="3", download_status="downloading")
    trashed = await add_gallery(
        db_session, source_id="4", download_status="downloading", deleted_at=utc(2026, 10, 30, 8, 0)
    )
    db_session.add(Image(gallery_id=kept.id, filename="001.jpg", page_num=1))
    await db_session.commit()
    await add_job(db_session, status="done", gallery_id=kept.id, stop_requested_at=utc(2026, 10, 30, 9, 0))
    await add_job(db_session, status="queued", gallery_id=active.id)

    with patch("core.database.AsyncSessionLocal", db_session_factory):
        settled = await _settle_orphan_downloading_galleries()

    assert settled == 2
    async with db_session_factory() as s:
        statuses = {g.id: g.download_status for g in (await s.execute(select(Gallery))).scalars()}
    assert statuses[kept.id] == "partial"
    assert statuses[empty.id] == "proxy_only"
    assert statuses[active.id] == "downloading"  # its job will import into it again
    assert statuses[trashed.id] == "downloading"  # BE-T17: a trashed gallery is never touched
