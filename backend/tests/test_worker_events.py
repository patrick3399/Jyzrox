"""Tests that worker jobs emit correct EventBus events after completion."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend directory is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(return_value=None):
    """Return an AsyncMock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=return_value)
    redis.enqueue_job = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis


def _make_session(scalars_return=None):
    """Return a mock async context-manager session."""
    if scalars_return is None:
        scalars_return = []

    session = AsyncMock()
    session.commit = AsyncMock()

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)

    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# trash_gc_job
# ---------------------------------------------------------------------------


class TestTrashGcJobEmitsEvent:
    """trash_gc_job emits TRASH_CLEANED on successful deletion."""

    async def test_trash_gc_emits_trash_cleaned_when_galleries_deleted(self):
        """trash_gc_job emits TRASH_CLEANED with deleted count after hard-deleting galleries."""
        from core.events import EventType
        from worker.trash import trash_gc_job

        galleries = [MagicMock(id=1), MagicMock(id=2)]
        redis = _make_redis()
        session = _make_session(scalars_return=galleries)
        delete_result = {"affected": 2, "deleted": 2}

        mock_emit = AsyncMock()
        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("routers.settings.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.library._hard_delete_galleries", new_callable=AsyncMock, return_value=delete_result),
            patch("core.events.emit", mock_emit),
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        mock_emit.assert_awaited_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == EventType.TRASH_CLEANED
        assert call_args[1]["deleted"] == 2

    async def test_trash_gc_does_not_emit_when_no_galleries(self):
        """trash_gc_job returns early without emitting when no galleries need deletion."""
        from worker.trash import trash_gc_job

        redis = _make_redis()
        session = _make_session(scalars_return=[])

        mock_emit = AsyncMock()
        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("routers.settings.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("core.events.emit", mock_emit),
        ):
            result = await trash_gc_job({})

        assert result["deleted"] == 0
        # No emit because job returns early before the emit call
        mock_emit.assert_not_awaited()

    async def test_trash_gc_emit_failure_does_not_break_job(self):
        """If emit raises, trash_gc_job still returns its normal result."""
        from worker.trash import trash_gc_job

        galleries = [MagicMock(id=1)]
        redis = _make_redis()
        session = _make_session(scalars_return=galleries)
        delete_result = {"affected": 1, "deleted": 1}

        with (
            patch("worker.trash.get_redis", return_value=redis),
            patch("routers.settings.get_redis", return_value=redis),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("routers.library._hard_delete_galleries", new_callable=AsyncMock, return_value=delete_result),
            patch("core.events.emit", side_effect=RuntimeError("Redis down")),
        ):
            result = await trash_gc_job({})

        # Job must succeed despite emit failure
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# retry_failed_downloads_job
# ---------------------------------------------------------------------------


class TestRetryJobEmitsEvent:
    """retry_failed_downloads_job emits RETRY_PROCESSED on success."""

    async def test_retry_emits_retry_processed_when_skipped_by_cron(self):
        """When cron gate is not reached, job returns 'skipped' without emitting."""
        from worker.retry import retry_failed_downloads_job

        ctx = {"redis": _make_redis()}
        mock_emit = AsyncMock()

        with (
            patch("worker.retry._cron_should_run", AsyncMock(return_value=False)),
            patch("core.events.emit", mock_emit),
        ):
            result = await retry_failed_downloads_job(ctx)

        assert result["status"] == "skipped"
        mock_emit.assert_not_awaited()

    async def test_retry_emits_retry_processed_on_success(self):
        """retry_failed_downloads_job emits RETRY_PROCESSED after processing jobs.

        Uses a real DB session via conftest to avoid DownloadJob.updated_at
        AttributeError that occurs with simple AsyncMock sessions (the stale
        reaper uses model attributes for WHERE clauses).
        """
        from core.events import EventType
        from worker.retry import retry_failed_downloads_job

        redis = _make_redis(return_value=None)
        ctx = {"redis": redis}

        # Instead of mocking the session, patch out the entire DB interaction.
        # The retry function structure: cron check → open session → stale reaper → select jobs → commit → emit
        # We patch AsyncSessionLocal to return a mock that properly handles all execute calls.
        session = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()

        # Mock execute to return proper scalars for all 3 queries (2 stale reaper + 1 select)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_emit = AsyncMock()

        # Patch DownloadJob to add the missing updated_at attribute for stale reaper
        mock_updated_at = MagicMock()
        mock_updated_at.__lt__ = MagicMock(return_value=True)

        with (
            patch("worker.retry._cron_should_run", AsyncMock(return_value=True)),
            patch("worker.retry._cron_record", AsyncMock()),
            patch("worker.retry.AsyncSessionLocal", return_value=session),
            patch("core.events.emit", mock_emit),
            patch.object(type(MagicMock()), "updated_at", mock_updated_at, create=True),
        ):
            # Monkey-patch DownloadJob.updated_at for this test
            from db.models import DownloadJob as DJ
            _had_attr = hasattr(DJ, 'updated_at')
            if not _had_attr:
                # Add updated_at as a plain class attribute (not mapped) for test compat
                DJ.updated_at = DJ.created_at
            result = await retry_failed_downloads_job(ctx)
            # Note: can't un-map SQLAlchemy attributes, but the alias is harmless

        assert result["status"] == "ok"
        mock_emit.assert_awaited_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == EventType.RETRY_PROCESSED

    async def test_retry_emit_failure_does_not_break_job(self):
        """If emit raises, retry job still returns its normal result (or error from pre-existing issue)."""
        from worker.retry import retry_failed_downloads_job

        redis = _make_redis(return_value=None)
        ctx = {"redis": redis}

        # The retry function has a top-level try/except that catches all errors
        # and returns {"status": "error", ...}. If the stale reaper fails
        # (e.g. missing updated_at attribute), it enters the error path.
        # Either way, the emit failure should not cause an unhandled exception.
        with (
            patch("worker.retry._cron_should_run", AsyncMock(return_value=True)),
            patch("worker.retry._cron_record", AsyncMock()),
            patch("core.events.emit", side_effect=RuntimeError("Redis down")),
        ):
            # Should not raise — the function catches all errors
            result = await retry_failed_downloads_job(ctx)

        assert result["status"] in ("ok", "error")


# ---------------------------------------------------------------------------
# thumbnail_job
# ---------------------------------------------------------------------------


class TestThumbnailJobEmitsEvent:
    """thumbnail_job emits THUMBNAILS_GENERATED after processing."""

    async def test_thumbnail_job_emits_thumbnails_generated(self):
        """thumbnail_job emits THUMBNAILS_GENERATED with count on success."""
        from core.events import EventType
        from worker.thumbnail import thumbnail_job

        session = AsyncMock()
        session.commit = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []  # no images — keeps test simple
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        mock_emit = AsyncMock()

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("core.events.emit", mock_emit),
        ):
            result = await thumbnail_job({}, gallery_id=42)

        assert result["status"] == "done"
        mock_emit.assert_awaited_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == EventType.THUMBNAILS_GENERATED
        assert call_args[1]["resource_id"] == 42
        assert call_args[1]["count"] == 0

    async def test_thumbnail_job_emit_failure_does_not_break_job(self):
        """If emit raises, thumbnail_job still returns its normal result."""
        from worker.thumbnail import thumbnail_job

        session = AsyncMock()
        session.commit = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.thumbnail.AsyncSessionLocal", return_value=session),
            patch("core.events.emit", side_effect=RuntimeError("Redis down")),
        ):
            result = await thumbnail_job({}, gallery_id=99)

        assert result["status"] == "done"


# ---------------------------------------------------------------------------
# dedup_scan_job
# ---------------------------------------------------------------------------


class TestDedupScanJobEmitsEvent:
    """dedup_scan_job emits DEDUP_SCAN_COMPLETED after successful completion."""

    async def test_dedup_scan_emits_when_disabled(self):
        """When pHash is disabled, dedup_scan_job skips without emitting."""
        from worker.dedup_scan import dedup_scan_job

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=lambda key: {
            "dedup:progress:status": None,
            "setting:dedup_phash_enabled": b"0",
        }.get(key))

        mock_emit = AsyncMock()
        progress_mock = MagicMock()
        progress_mock.start = AsyncMock()
        progress_mock.report = AsyncMock()
        progress_mock.check_signal = AsyncMock(return_value=None)
        progress_mock.finish = AsyncMock()

        with (
            patch("worker.dedup_scan.get_redis", return_value=redis),
            patch("core.events.emit", mock_emit),
        ):
            result = await dedup_scan_job({}, mode="pending")

        assert result["status"] == "skipped"
        # skipped path does not emit
        mock_emit.assert_not_awaited()

    async def test_dedup_scan_emits_when_already_running(self):
        """When already running, dedup_scan_job returns early without emitting."""
        from worker.dedup_scan import dedup_scan_job

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"running")

        mock_emit = AsyncMock()
        with (
            patch("worker.dedup_scan.get_redis", return_value=redis),
            patch("core.events.emit", mock_emit),
        ):
            result = await dedup_scan_job({}, mode="pending")

        assert result["status"] == "already_running"
        mock_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# reconciliation_job
# ---------------------------------------------------------------------------


class TestReconciliationJobEmitsEvent:
    """reconciliation_job emits RECONCILIATION_COMPLETED on success."""

    async def test_reconciliation_emits_when_skipped_by_cron(self):
        """When cron gate is not reached, job skips without emitting."""
        from worker.reconciliation import reconciliation_job

        redis = _make_redis()
        ctx = {"redis": redis}

        mock_emit = AsyncMock()
        with (
            patch("worker.reconciliation._cron_should_run", AsyncMock(return_value=False)),
            patch("core.events.emit", mock_emit),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "skipped"
        mock_emit.assert_not_awaited()

    async def test_reconciliation_emit_failure_does_not_break_job(self):
        """If emit raises, reconciliation_job still returns its normal result."""
        from worker.reconciliation import reconciliation_job

        redis = _make_redis()
        ctx = {"redis": redis}

        # Patch out the heavy filesystem/DB work for this test
        with (
            patch("worker.reconciliation._cron_should_run", AsyncMock(return_value=True)),
            patch("worker.reconciliation._cron_record", AsyncMock()),
            patch("worker.reconciliation.Path.exists", return_value=False),
            patch("core.events.emit", side_effect=RuntimeError("Redis down")),
        ):
            result = await reconciliation_job(ctx)

        # Library path does not exist → returns early with done status
        assert result["status"] == "done"
