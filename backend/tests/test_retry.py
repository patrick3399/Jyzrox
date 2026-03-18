"""
Tests for retry_failed_downloads_job worker function.

Tests the cron logic, exponential backoff calculation, and job re-queuing.
Uses mocked DB sessions and Redis to avoid external dependencies.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

        with (
            patch("worker.retry._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.retry._cron_record", new_callable=AsyncMock),
            patch("worker.retry.AsyncSessionLocal", return_value=mock_session),
            patch("core.events.emit_safe", new_callable=AsyncMock),
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
        mock_redis.enqueue_job.assert_called_once()

    async def test_retries_partial_job(self):
        """Should re-queue a partial job."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.enqueue_job = AsyncMock()

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
        """If ARQ enqueue fails, job should be reverted to failed status."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.enqueue_job = AsyncMock(side_effect=Exception("Redis down"))

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

        # Job with retry_count=0, max_retries=5 (matching Redis setting)
        # Redis max_retries only affects new jobs; the job's own max_retries
        # column is what the SQL query uses. This test verifies settings are
        # read without error and that backoff uses the custom base_delay.
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


class TestImageValidation:
    """Unit tests for _validate_image_magic helper."""

    def test_valid_jpeg(self, tmp_path):
        """JPEG magic bytes should validate with .jpg extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)
        assert _validate_image_magic(f) is True

    def test_valid_png(self, tmp_path):
        """PNG magic bytes should validate with .png extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.png"
        f.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        assert _validate_image_magic(f) is True

    def test_valid_gif(self, tmp_path):
        """GIF magic bytes should validate with .gif extension."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.gif"
        f.write_bytes(b'GIF89a' + b'\x00' * 100)
        assert _validate_image_magic(f) is True

    def test_wrong_extension(self, tmp_path):
        """JPEG magic bytes with .png extension should fail."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.png"
        f.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)
        assert _validate_image_magic(f) is False

    def test_truncated_file(self, tmp_path):
        """File with less than 3 bytes should fail."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b'\xff\xd8')
        assert _validate_image_magic(f) is False

    def test_corrupt_data(self, tmp_path):
        """Random bytes should fail validation."""
        from worker.helpers import _validate_image_magic

        f = tmp_path / "test.jpg"
        f.write_bytes(b'\x00\x00\x00\x00' + b'\x00' * 100)
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
        f.write_bytes(b'RIFF\x00\x00\x00\x00WEBP' + b'\x00' * 100)
        assert _validate_image_magic(f) is True
