"""
Unit tests for the M7 worker startup recovery logic.

Tests cover:
  - mark_failed strategy: running jobs are marked failed instead of re-enqueued
  - auto_retry strategy on paused jobs: pause key deleted, job re-enqueued with
    incremented retry_count
  - SYSTEM_WORKER_RECOVERED event is emitted with the correct recovery counts
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend directory is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Yield items as an async iterator (mimics Redis scan_iter)."""
    for item in items:
        yield item


def _make_redis(strategy_running: str | None = None, strategy_paused: str | None = None):
    """Return an AsyncMock Redis with optional recovery strategy pre-seeded."""
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()
    redis.delete = AsyncMock()
    redis.scan_iter = MagicMock(return_value=_async_iter([]))
    redis.lpush = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.ltrim = AsyncMock()
    redis.set = AsyncMock()
    redis.pipeline = MagicMock(return_value=AsyncMock())

    async def _get(key):
        if key == "setting:recovery_running" and strategy_running is not None:
            return strategy_running.encode()
        if key == "setting:recovery_paused" and strategy_paused is not None:
            return strategy_paused.encode()
        return None

    redis.get = AsyncMock(side_effect=_get)
    return redis


def _make_job(
    job_id: str = "job-1",
    status: str = "running",
    url: str = "https://example.com/gallery/1",
    retry_count: int = 0,
    gallery_id: int | None = None,
):
    """Return a MagicMock DownloadJob with the given attributes."""
    job = MagicMock()
    job.id = job_id
    job.status = status
    job.url = url
    job.retry_count = retry_count
    job.gallery_id = gallery_id
    job.max_retries = 3
    job.error = None
    job.finished_at = None
    return job


def _make_session(running_jobs=None, queued_jobs=None, paused_jobs=None):
    """Return an AsyncMock DB session that returns the given job lists.

    Query order in startup():
      1: select running jobs
      2: image count batch + gallery update (only when running_jobs non-empty
         with gallery_ids — up to 2 extra queries)
      N-2: select queued jobs
      N-1: select paused jobs
      N:   update subscription groups
    """
    running_jobs = running_jobs or []
    queued_jobs = queued_jobs or []
    paused_jobs = paused_jobs or []

    # Build the sequence of responses based on whether running_jobs exist
    # and whether they have gallery_ids (which triggers the stuck-fix queries).
    responses = []

    # 1: select running jobs
    responses.append(("scalars", running_jobs))

    if running_jobs:
        gallery_ids = [j.gallery_id for j in running_jobs if j.gallery_id is not None]
        if gallery_ids:
            # image count batch query (returns raw rows, not scalars)
            responses.append(("rows", []))
            # gallery update — returns a result (no scalars needed)
            responses.append(("empty", []))

    # select queued jobs
    responses.append(("scalars", queued_jobs))
    # select paused jobs
    responses.append(("scalars", paused_jobs))
    # subscription group reset (UPDATE)
    responses.append(("empty", []))

    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    call_idx = [0]

    async def _execute(stmt, *_args, **_kwargs):
        result = MagicMock()
        scalars = MagicMock()

        idx = call_idx[0]
        call_idx[0] += 1

        if idx < len(responses):
            resp_type, data = responses[idx]
        else:
            resp_type, data = "empty", []

        if resp_type == "scalars":
            scalars.all.return_value = data
        elif resp_type == "rows":
            result.all.return_value = data
            scalars.all.return_value = []
        else:
            scalars.all.return_value = []
            result.all.return_value = []

        result.scalars.return_value = scalars
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@contextmanager
def _startup_patches(session, mock_enqueue=None, mock_emit=None):
    """Context manager that patches all startup() side-effects.

    This covers: init_redis, log_handler, plugins, site_config,
    adaptive_engine, ensure_venv, AsyncSessionLocal, enqueue_download_job,
    emit_safe, _watcher, asyncio helpers, and glob.
    """
    if mock_enqueue is None:
        mock_enqueue = AsyncMock()
    if mock_emit is None:
        mock_emit = AsyncMock()

    mock_adaptive = MagicMock()
    mock_adaptive.load_all_from_db = AsyncMock(return_value=0)

    mock_site_config = MagicMock()
    mock_site_config.start_listener = AsyncMock()

    with (
        patch("worker.init_redis", new_callable=AsyncMock),
        patch("core.log_handler.install_log_handler"),
        patch("core.log_handler.apply_log_level_from_redis", new_callable=AsyncMock),
        patch("plugins.init_plugins", new_callable=AsyncMock),
        patch("core.site_config.site_config_service", mock_site_config),
        patch("core.adaptive.adaptive_engine", mock_adaptive),
        patch("worker.ensure_venv", new_callable=AsyncMock),
        patch("core.database.AsyncSessionLocal", return_value=session),
        patch("worker.enqueue_download_job", mock_enqueue),
        patch("worker.compute_arq_job_id", side_effect=lambda jid, rc: f"arq-{jid}-{rc}"),
        patch("core.events.emit_safe", mock_emit),
        patch("worker._watcher") as mock_watcher,
        patch("worker.asyncio.ensure_future"),
        patch("worker.asyncio.get_event_loop", return_value=MagicMock()),
        patch("worker.get_all_library_paths", new_callable=AsyncMock, return_value=[]),
        patch("glob.glob", return_value=[]),
    ):
        mock_watcher.start = MagicMock()
        yield {"enqueue": mock_enqueue, "emit": mock_emit}


async def _run_startup(redis, session, mock_enqueue=None, mock_emit=None):
    """Run worker.startup() with all side-effects patched."""
    with _startup_patches(session, mock_enqueue, mock_emit) as mocks:
        from worker import startup

        await startup({"redis": redis})
    return mocks


# ---------------------------------------------------------------------------
# Running-job recovery: mark_failed strategy
# ---------------------------------------------------------------------------


class TestStartupMarkFailedStrategy:
    """When setting:recovery_running = mark_failed, running jobs are failed."""

    async def test_startup_mark_failed_strategy_sets_job_status_to_failed(self):
        """Running jobs must be marked as failed when running_strategy=mark_failed."""
        job = _make_job("job-abc", status="running")
        redis = _make_redis(strategy_running="mark_failed", strategy_paused="keep_paused")
        session = _make_session(running_jobs=[job])

        mock_enqueue = AsyncMock()
        await _run_startup(redis, session, mock_enqueue=mock_enqueue)

        assert job.status == "failed"
        assert job.error == "Marked failed by recovery policy"
        assert job.finished_at is not None
        mock_enqueue.assert_not_awaited()

    async def test_startup_mark_failed_strategy_emits_correct_counts(self):
        """mark_failed strategy: running_failed count is correct in emitted event."""
        jobs = [_make_job(f"job-{i}", status="running") for i in range(3)]
        redis = _make_redis(strategy_running="mark_failed", strategy_paused="keep_paused")
        session = _make_session(running_jobs=jobs)

        mock_emit = AsyncMock()
        await _run_startup(redis, session, mock_emit=mock_emit)

        mock_emit.assert_awaited_once()
        _, kwargs = mock_emit.call_args
        assert kwargs.get("running_failed") == 3
        assert kwargs.get("running_retried") == 0


# ---------------------------------------------------------------------------
# Paused-job recovery: auto_retry strategy
# ---------------------------------------------------------------------------


class TestStartupPausedAutoRetry:
    """When setting:recovery_paused = auto_retry, paused jobs are re-enqueued."""

    async def test_startup_paused_auto_retry_deletes_pause_key_and_reenqueues(self):
        """auto_retry on paused jobs: pause key deleted, job re-enqueued as queued."""
        job = _make_job("job-p1", status="paused", retry_count=0)
        redis = _make_redis(strategy_running="auto_retry", strategy_paused="auto_retry")
        session = _make_session(paused_jobs=[job])

        mock_enqueue = AsyncMock()
        await _run_startup(redis, session, mock_enqueue=mock_enqueue)

        redis.delete.assert_any_call("download:pause:job-p1")
        assert job.status == "queued"
        assert job.retry_count == 1
        assert job.error is None
        mock_enqueue.assert_awaited()

    async def test_startup_paused_auto_retry_emits_correct_counts(self):
        """auto_retry strategy: paused_retried count is correct in emitted event."""
        jobs = [_make_job(f"job-p{i}", status="paused", retry_count=0) for i in range(2)]
        redis = _make_redis(strategy_running="auto_retry", strategy_paused="auto_retry")
        session = _make_session(paused_jobs=jobs)

        mock_emit = AsyncMock()
        await _run_startup(redis, session, mock_emit=mock_emit)

        mock_emit.assert_awaited_once()
        _, kwargs = mock_emit.call_args
        assert kwargs.get("paused_retried") == 2
        assert kwargs.get("paused_kept") == 0


# ---------------------------------------------------------------------------
# Event emission: SYSTEM_WORKER_RECOVERED
# ---------------------------------------------------------------------------


class TestStartupEmitsWorkerRecoveredEvent:
    """startup() must emit SYSTEM_WORKER_RECOVERED with correct recovery counts."""

    async def test_startup_emits_worker_recovered_event_with_correct_counts(self):
        """After recovery, emit_safe is called with SYSTEM_WORKER_RECOVERED and counts."""
        from core.events import EventType

        running_job = _make_job("job-r1", status="running")
        paused_job = _make_job("job-p1", status="paused")
        redis = _make_redis(strategy_running="auto_retry", strategy_paused="keep_paused")
        session = _make_session(running_jobs=[running_job], paused_jobs=[paused_job])

        mock_emit = AsyncMock()
        await _run_startup(redis, session, mock_emit=mock_emit)

        mock_emit.assert_awaited_once()
        args, kwargs = mock_emit.call_args
        assert args[0] == EventType.SYSTEM_WORKER_RECOVERED
        assert kwargs.get("resource_type") == "system"
        assert kwargs.get("running_retried") == 1
        assert kwargs.get("running_failed") == 0
        assert kwargs.get("paused_kept") == 1
        assert kwargs.get("paused_retried") == 0

    async def test_startup_emits_worker_recovered_event_includes_strategy_fields(self):
        """SYSTEM_WORKER_RECOVERED event includes running_strategy and paused_strategy."""
        redis = _make_redis(strategy_running="mark_failed", strategy_paused="mark_failed")
        session = _make_session()

        mock_emit = AsyncMock()
        await _run_startup(redis, session, mock_emit=mock_emit)

        mock_emit.assert_awaited_once()
        _, kwargs = mock_emit.call_args
        assert kwargs.get("running_strategy") == "mark_failed"
        assert kwargs.get("paused_strategy") == "mark_failed"

    async def test_startup_no_stale_jobs_still_emits_recovered_event(self):
        """emit_safe is called even when there are no stale jobs to recover."""
        from core.events import EventType

        redis = _make_redis()
        session = _make_session()

        mock_emit = AsyncMock()
        await _run_startup(redis, session, mock_emit=mock_emit)

        mock_emit.assert_awaited_once()
        args, _ = mock_emit.call_args
        assert args[0] == EventType.SYSTEM_WORKER_RECOVERED
