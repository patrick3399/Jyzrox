"""
Tests for retry_failed_downloads_job worker function.

Tests the cron logic, exponential backoff calculation, and job re-queuing.
Uses mocked DB sessions and Redis to avoid external dependencies.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_job(
    status="failed",
    retry_count=0,
    max_retries=3,
    next_retry_at=None,
    url="https://e-hentai.org/g/123/abc/",
    source="ehentai",
    progress=None,
):
    """Create a mock DownloadJob object."""
    job = MagicMock()
    job.id = uuid.uuid4()
    job.url = url
    job.source = source
    job.status = status
    job.retry_count = retry_count
    job.max_retries = max_retries
    job.next_retry_at = next_retry_at
    job.finished_at = datetime.now(UTC)
    job.error = "Download failed: timeout"
    job.progress = progress or {}
    job.created_at = datetime.now(UTC) - timedelta(hours=1)
    return job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRetryFailedDownloadsJob:
    """Unit tests for retry_failed_downloads_job."""

    async def test_skipped_when_cron_not_due(self):
        """Should return skipped when _cron_should_run returns False."""
        with patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=False):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": AsyncMock()})
            assert result["status"] == "skipped"

    async def test_disabled_via_redis_setting(self):
        """Should return disabled when setting:retry_enabled is '0'."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"0")

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})
            assert result["status"] == "disabled"

    async def test_retries_failed_job(self):
        """Should re-queue a failed job with incremented retry_count."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # all defaults
        mock_redis.enqueue_job = AsyncMock()

        mock_job = _make_mock_job(status="failed", retry_count=0)

        mock_session = AsyncMock()
        # execute() is called 3 times:
        #   1. UPDATE stale running jobs  → empty result
        #   2. UPDATE stale queued jobs   → empty result
        #   3. SELECT retry jobs          → [mock_job]
        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []
        mock_retry_result = MagicMock()
        mock_retry_result.scalars.return_value.all.return_value = [mock_job]
        mock_session.execute = AsyncMock(side_effect=[mock_stale_result, mock_stale_result, mock_retry_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_enqueue = AsyncMock()
        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", mock_enqueue),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})

        assert result["status"] == "ok"
        assert result["retried"] == 1
        assert result["stale_reaped"] == 0
        assert mock_job.retry_count == 1
        assert mock_job.status == "queued"
        assert mock_job.finished_at is None
        assert mock_job.error is None
        mock_enqueue.assert_called_once()

    async def test_retries_partial_job(self):
        """Should re-queue a partial job."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_job = _make_mock_job(status="partial", retry_count=1, progress={"failed_pages": [3, 7]})

        mock_session = AsyncMock()
        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []
        mock_retry_result = MagicMock()
        mock_retry_result.scalars.return_value.all.return_value = [mock_job]
        mock_session.execute = AsyncMock(side_effect=[mock_stale_result, mock_stale_result, mock_retry_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})

        assert result["retried"] == 1
        assert mock_job.retry_count == 2

    async def test_exponential_backoff(self):
        """next_retry_at should use exponential backoff with cap at 24h."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # base_delay=5
        mock_redis.enqueue_job = AsyncMock()

        mock_job = _make_mock_job(status="failed", retry_count=0)

        mock_session = AsyncMock()
        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []
        mock_retry_result = MagicMock()
        mock_retry_result.scalars.return_value.all.return_value = [mock_job]
        mock_session.execute = AsyncMock(side_effect=[mock_stale_result, mock_stale_result, mock_retry_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            before = datetime.now(UTC)
            await retry_failed_downloads_job({"redis": mock_redis})

        # After retry_count becomes 1, backoff = 5 * 2^1 = 10 minutes
        assert mock_job.next_retry_at is not None
        expected_min = before + timedelta(minutes=9)  # allow some slack
        expected_max = before + timedelta(minutes=11)
        assert expected_min <= mock_job.next_retry_at <= expected_max

    async def test_no_jobs_to_retry(self):
        """Should return idle when no retryable jobs found."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_empty_result = MagicMock()
        mock_empty_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[mock_empty_result, mock_empty_result, mock_empty_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})

        assert result["status"] == "ok"
        assert result["retried"] == 0
        assert result["stale_reaped"] == 0

    async def test_enqueue_failure_reverts_job(self):
        """If enqueue fails, job should be reverted to failed status."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_job = _make_mock_job(status="failed", retry_count=0)

        mock_session = AsyncMock()
        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []
        mock_retry_result = MagicMock()
        mock_retry_result.scalars.return_value.all.return_value = [mock_job]
        mock_session.execute = AsyncMock(side_effect=[mock_stale_result, mock_stale_result, mock_retry_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", new_callable=AsyncMock, side_effect=Exception("Redis down")),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})

        assert result["skipped"] == 1
        assert mock_job.retry_count == 0  # reverted
        assert mock_job.status == "failed"  # reverted

    async def test_custom_redis_settings(self):
        """Should respect custom max_retries and base_delay from Redis."""
        mock_redis = AsyncMock()

        def _get_side_effect(key):
            mapping = {
                "setting:retry_enabled": b"1",
                "setting:retry_max_retries": b"5",
                "setting:retry_base_delay_minutes": b"10",
            }
            return mapping.get(key)

        mock_redis.get = AsyncMock(side_effect=_get_side_effect)
        mock_redis.enqueue_job = AsyncMock()

        # The global retry_max_retries setting is the authoritative cap for the
        # retry cron (see TestRetryRespectsGlobalMaxRetries). This test verifies
        # settings are read without error and that backoff uses the custom
        # base_delay. (Execute is fully mocked here, so the WHERE clause is not
        # actually evaluated — the global-cap behavior is covered by the
        # real-DB tests in TestRetryRespectsGlobalMaxRetries.)
        mock_job = _make_mock_job(status="failed", retry_count=0, max_retries=5)

        mock_session = AsyncMock()
        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []
        mock_retry_result = MagicMock()
        mock_retry_result.scalars.return_value.all.return_value = [mock_job]
        mock_session.execute = AsyncMock(side_effect=[mock_stale_result, mock_stale_result, mock_retry_result])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": mock_redis})

        assert result["retried"] == 1
        # With base_delay=10, retry_count becomes 1: backoff = 10 * 2^1 = 20 min
        expected_backoff = timedelta(minutes=20)
        # Check it's roughly 20 minutes from now
        now = datetime.now(UTC)
        assert mock_job.next_retry_at >= now + expected_backoff - timedelta(seconds=5)


class TestStaleReaperUsesHeartbeat:
    """Regression tests for edge case #33: the stale reaper marks ANY running
    job older than one hour as failed based on `created_at`, ignoring the
    `progress.last_update_at` heartbeat the worker writes on every progress
    tick. A real long-running download that is actively making progress is
    wrongly killed. Runs against the real SQLite engine.
    """

    async def _insert_running_job(
        self,
        session,
        *,
        created_minutes_ago,
        last_update_minutes_ago,
        admission_token=None,
    ):
        from db.models import DownloadJob

        now = datetime.now(UTC)
        progress = {}
        if last_update_minutes_ago is not None:
            progress = {"last_update_at": (now - timedelta(minutes=last_update_minutes_ago)).isoformat()}
        job = DownloadJob(
            id=uuid.uuid4(),
            url="https://e-hentai.org/g/123/abc/",
            source="ehentai",
            status="running",
            retry_count=0,
            max_retries=3,
            created_at=now - timedelta(minutes=created_minutes_ago),
            progress=progress,
            admission_key="ehentai" if admission_token else None,
            admission_token=admission_token,
        )
        session.add(job)
        await session.commit()
        return job.id

    async def test_actively_progressing_long_job_is_not_reaped(self, db_session, db_session_factory):
        """A job created 2h ago but whose heartbeat is 5 min old is alive and
        must NOT be reaped, even though created_at is well past the 1h mark."""
        alive_id = await self._insert_running_job(db_session, created_minutes_ago=120, last_update_minutes_ago=5)
        stuck_id = await self._insert_running_job(db_session, created_minutes_ago=120, last_update_minutes_ago=90)
        never_progressed_id = await self._insert_running_job(
            db_session, created_minutes_ago=120, last_update_minutes_ago=None
        )

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", db_session_factory),
            patch("worker.retry.enqueue_download_job", new_callable=AsyncMock),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": AsyncMock(get=AsyncMock(return_value=None))})

        from db.models import DownloadJob

        alive = await db_session.get(DownloadJob, alive_id)
        assert alive.status == "running", "a job with a fresh heartbeat must not be reaped"

        # Only the stuck job and the never-progressed job (heartbeat falls back to
        # created_at) are stale.
        assert result["stale_reaped"] == 2
        stuck = await db_session.get(DownloadJob, stuck_id)
        never = await db_session.get(DownloadJob, never_progressed_id)
        assert stuck.status != "running"
        assert never.status != "running"

    async def test_stale_running_token_owner_is_not_reaped_or_retried(self, db_session, db_session_factory):
        """A live fenced execution is authoritative even without a recent progress tick."""
        token = uuid.uuid4()
        job_id = await self._insert_running_job(
            db_session,
            created_minutes_ago=120,
            last_update_minutes_ago=90,
            admission_token=token,
        )
        enqueue = AsyncMock()

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", db_session_factory),
            patch("worker.retry.enqueue_download_job", enqueue),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": AsyncMock(get=AsyncMock(return_value=None))})

        from db.models import DownloadJob

        db_session.expire_all()
        job = await db_session.get(DownloadJob, job_id)
        assert result["stale_reaped"] == 0
        assert job.status == "running"
        assert job.admission_token == token
        assert job.retry_count == 0
        enqueue.assert_not_awaited()


class TestStaleQueuedReaperChecksSaqMembership:
    """Regression tests for edge case #34: the queued stale reaper fails any
    queued job older than 30 min based on `created_at`, so a legitimate queued
    backlog (low concurrency / source semaphore wait) is wrongly failed and then
    re-enqueued in the same run — producing duplicate SAQ entries. A queued job
    that still has a live SAQ queue entry must be preserved.
    """

    async def _insert_queued_job(self, session, *, created_minutes_ago):
        from db.models import DownloadJob

        job = DownloadJob(
            id=uuid.uuid4(),
            url="https://e-hentai.org/g/123/abc/",
            source="ehentai",
            status="queued",
            retry_count=0,
            max_retries=3,
            created_at=datetime.now(UTC) - timedelta(minutes=created_minutes_ago),
            progress={},
        )
        session.add(job)
        await session.commit()
        return job.id

    async def test_queued_job_with_live_saq_entry_is_not_reaped(self, db_session, db_session_factory):
        from saq.job import Status

        live_id = await self._insert_queued_job(db_session, created_minutes_ago=40)
        orphan_id = await self._insert_queued_job(db_session, created_minutes_ago=40)

        live_saq_job = MagicMock()
        live_saq_job.status = Status.QUEUED

        async def _lookup(key):
            # The live job still sits in the SAQ queue; the orphan has no entry.
            return live_saq_job if key == str(live_id) else None

        mock_queue = MagicMock()
        mock_queue.job = AsyncMock(side_effect=_lookup)
        mock_enqueue = AsyncMock()

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", db_session_factory),
            patch("worker.retry.get_queue", return_value=mock_queue),
            patch("worker.retry.enqueue_download_job", mock_enqueue),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": AsyncMock(get=AsyncMock(return_value=None))})

        # A missing transport entry is repaired as delivery loss. Waiting for a
        # source slot is not a failed download and must not consume retry budget.
        assert result["stale_reaped"] == 0, "queued admission work must never be converted to failed"

        from db.models import DownloadJob

        orphan = await db_session.get(DownloadJob, orphan_id)
        assert orphan.status == "queued"
        assert orphan.retry_count == 0
        mock_enqueue.assert_awaited_once()

        live = await db_session.get(DownloadJob, live_id)
        assert live.status == "queued"


class TestRetryRespectsGlobalMaxRetries:
    """Regression tests for edge case #35: the operator-facing global
    `setting:retry_max_retries` is read but unused — the retry cron compares
    against the per-job `DownloadJob.max_retries` column (always the DB default
    of 3) instead of the live global setting, so changing the global has no
    effect. These tests run the real SQL query against the SQLite engine so the
    WHERE clause is actually evaluated.
    """

    async def _insert_job(self, session, *, retry_count, max_retries=3, status="failed"):
        from db.models import DownloadJob

        job = DownloadJob(
            id=uuid.uuid4(),
            url="https://e-hentai.org/g/123/abc/",
            source="ehentai",
            status=status,
            retry_count=retry_count,
            max_retries=max_retries,
            created_at=datetime.now(UTC),
            error="boom",
        )
        session.add(job)
        await session.commit()
        return job.id

    def _redis_with_global(self, value: bytes):
        redis = AsyncMock()

        def _get(key):
            return {"setting:retry_max_retries": value}.get(key)

        redis.get = AsyncMock(side_effect=_get)
        return redis

    async def test_raising_global_max_retries_retries_job_past_per_job_default(self, db_session, db_session_factory):
        """Operator raises global retry_max_retries to 5; a job that exhausted
        the per-job default (retry_count=3, max_retries=3) must now be retried."""
        job_id = await self._insert_job(db_session, retry_count=3, max_retries=3)
        redis = self._redis_with_global(b"5")

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", db_session_factory),
            patch("worker.retry.enqueue_download_job", new_callable=AsyncMock),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": redis})

        assert result["retried"] == 1, "global max_retries=5 should make a retry_count=3 job retryable"

        from db.models import DownloadJob

        refreshed = await db_session.get(DownloadJob, job_id)
        assert refreshed.status == "queued"
        assert refreshed.retry_count == 4

    async def test_lowering_global_max_retries_stops_retrying_job(self, db_session, db_session_factory):
        """Operator lowers global retry_max_retries to 1; a job with
        retry_count=1 (still under the per-job default of 3) must NOT be retried."""
        job_id = await self._insert_job(db_session, retry_count=1, max_retries=3)
        redis = self._redis_with_global(b"1")

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", db_session_factory),
            patch("worker.retry.enqueue_download_job", new_callable=AsyncMock),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            from worker.retry import retry_failed_downloads_job

            result = await retry_failed_downloads_job({"redis": redis})

        assert result["retried"] == 0, "global max_retries=1 should stop retrying a retry_count=1 job"

        from db.models import DownloadJob

        refreshed = await db_session.get(DownloadJob, job_id)
        assert refreshed.status == "failed"
        assert refreshed.retry_count == 1


class TestImageValidation:
    """Unit tests for _validate_image_magic helper."""

    def test_valid_jpeg(self, tmp_path):
        """JPEG magic bytes should validate with .jpg extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        assert _validate_image_magic(f) is True

    def test_valid_png(self, tmp_path):
        """PNG magic bytes should validate with .png extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert _validate_image_magic(f) is True

    def test_valid_gif(self, tmp_path):
        """GIF magic bytes should validate with .gif extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.gif"
        f.write_bytes(b"GIF89a" + b"\x00" * 100)
        assert _validate_image_magic(f) is True

    def test_wrong_extension(self, tmp_path):
        """JPEG magic bytes with .png extension should fail."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.png"
        f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        assert _validate_image_magic(f) is False

    def test_truncated_file(self, tmp_path):
        """File with less than 3 bytes should fail."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b"\xff\xd8")
        assert _validate_image_magic(f) is False

    def test_corrupt_data(self, tmp_path):
        """Random bytes should fail validation."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b"\x00\x00\x00\x00" + b"\x00" * 100)
        assert _validate_image_magic(f) is False

    def test_nonexistent_file(self, tmp_path):
        """Non-existent file should return False."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "nonexistent.jpg"
        assert _validate_image_magic(f) is False

    def test_webp_magic(self, tmp_path):
        """WebP RIFF+WEBP magic should validate."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.webp"
        # RIFF + 4 bytes size + WEBP
        f.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100)
        assert _validate_image_magic(f) is True
