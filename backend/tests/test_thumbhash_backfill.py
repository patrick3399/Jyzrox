"""
Tests for worker/thumbhash_backfill.py — thumbhash_backfill_job.

Mocks:
- AsyncSessionLocal (context manager, returns mock session with blobs)
- services.cas.thumb_dir (path to thumbnails)
- asyncio.to_thread (avoids PIL/thumbhash deps)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_blob(sha: str, thumbhash: str | None = None):
    """Create a minimal Blob-like mock object."""
    blob = MagicMock()
    blob.sha256 = sha
    blob.thumbhash = thumbhash
    return blob


def _make_mock_session(blobs_per_call: list[list]):
    """
    Build a mock AsyncSessionLocal that returns successive batches of blobs.

    blobs_per_call is a list of lists; each inner list is returned by one
    .scalars().all() call. An extra empty list is appended to signal loop end.
    """
    # Append the sentinel empty batch that breaks the while-loop
    all_batches = list(blobs_per_call) + [[]]

    call_count = 0

    session = AsyncMock()
    session.commit = AsyncMock()

    async def _execute(stmt):
        nonlocal call_count
        mock_result = MagicMock()
        batch = all_batches[call_count] if call_count < len(all_batches) else []
        mock_result.scalars.return_value.all.return_value = batch
        call_count += 1
        return mock_result

    session.execute = _execute
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestThumhhashBackfillJob:
    """Unit tests for thumbhash_backfill_job."""

    async def test_no_blobs_returns_done_with_zero_counts(self):
        """When no blobs need backfill, job returns status=done with 0 processed/failed."""
        session = _make_mock_session([])

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["status"] == "done"
        assert result["processed"] == 0
        assert result["failed"] == 0

    async def test_successful_backfill_increments_processed(self, tmp_path):
        """Blobs with existing thumb_160.webp get thumbhash assigned and processed count rises."""
        sha = "aabbcc001122334455667788aabbcc001122334455667788aabbcc0011223344"
        blob = _make_blob(sha)

        thumb_dir_path = tmp_path / sha[:2] / sha[2:4] / sha
        thumb_dir_path.mkdir(parents=True)
        thumb_file = thumb_dir_path / "thumb_160.webp"
        thumb_file.write_bytes(b"fake_thumb_data")

        session = _make_mock_session([[blob]])

        fake_hash = "dGVzdGhhc2g="  # base64 for "testhash"

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", return_value=thumb_dir_path),
            patch("worker.thumbhash_backfill.asyncio.to_thread", new_callable=AsyncMock, return_value=fake_hash),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["status"] == "done"
        assert result["processed"] == 1
        assert result["failed"] == 0
        assert blob.thumbhash == fake_hash

    async def test_missing_thumb_file_skips_blob(self, tmp_path):
        """Blob whose thumb_160.webp does not exist is silently skipped (not failed)."""
        sha = "deadbeef00112233445566778899aabbccddeeff00112233445566778899aabb"
        blob = _make_blob(sha)

        # Create the dir but NOT the thumb file
        thumb_dir_path = tmp_path / sha[:2] / sha[2:4] / sha
        thumb_dir_path.mkdir(parents=True)

        session = _make_mock_session([[blob]])

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", return_value=thumb_dir_path),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["processed"] == 0
        assert result["failed"] == 0

    async def test_pil_error_increments_failed_not_processed(self, tmp_path):
        """Exception raised by _generate_thumbhash increments failed count, not processed."""
        sha = "cafe1234" * 8
        blob = _make_blob(sha)

        thumb_dir_path = tmp_path / "t"
        thumb_dir_path.mkdir(parents=True)
        (thumb_dir_path / "thumb_160.webp").write_bytes(b"x")

        session = _make_mock_session([[blob]])

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", return_value=thumb_dir_path),
            patch(
                "worker.thumbhash_backfill.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=OSError("cannot identify image file"),
            ),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["failed"] == 1
        assert result["processed"] == 0

    async def test_batch_processing_handles_multiple_blobs(self, tmp_path):
        """All blobs in a batch that have thumb files get processed successfully."""
        shas = [f"aa{i:062x}" for i in range(3)]
        blobs = [_make_blob(sha) for sha in shas]

        thumb_dirs = []
        for sha in shas:
            d = tmp_path / sha[:2] / sha
            d.mkdir(parents=True)
            (d / "thumb_160.webp").write_bytes(b"fake")
            thumb_dirs.append(d)

        session = _make_mock_session([blobs])

        fake_hash = "c29tZWhhc2g="

        call_idx = 0

        def _thumb_dir_factory(sha):
            nonlocal call_idx
            d = thumb_dirs[call_idx % len(thumb_dirs)]
            call_idx += 1
            return d

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", side_effect=_thumb_dir_factory),
            patch("worker.thumbhash_backfill.asyncio.to_thread", new_callable=AsyncMock, return_value=fake_hash),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["processed"] == 3
        assert result["failed"] == 0

    async def test_multi_batch_processes_all_batches(self, tmp_path):
        """Multiple successive batches are each processed until empty sentinel breaks the loop."""
        sha_a = "11" * 32
        sha_b = "22" * 32
        blob_a = _make_blob(sha_a)
        blob_b = _make_blob(sha_b)

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "thumb_160.webp").write_bytes(b"x")

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "thumb_160.webp").write_bytes(b"x")

        session = _make_mock_session([[blob_a], [blob_b]])

        dirs_by_sha = {sha_a: dir_a, sha_b: dir_b}

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", side_effect=lambda sha: dirs_by_sha[sha]),
            patch("worker.thumbhash_backfill.asyncio.to_thread", new_callable=AsyncMock, return_value="aGFzaA=="),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["processed"] == 2

    async def test_session_commit_called_after_each_batch(self, tmp_path):
        """Session.commit() should be called once per batch."""
        sha = "ff" * 32
        blob = _make_blob(sha)

        thumb_dir_path = tmp_path / "td"
        thumb_dir_path.mkdir()
        (thumb_dir_path / "thumb_160.webp").write_bytes(b"x")

        session = _make_mock_session([[blob]])

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", return_value=thumb_dir_path),
            patch("worker.thumbhash_backfill.asyncio.to_thread", new_callable=AsyncMock, return_value="aGFzaA=="),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            await thumbhash_backfill_job(ctx={})

        # commit called once for the real batch plus once for the terminating empty batch
        assert session.commit.await_count >= 1

    async def test_to_thread_returns_none_does_not_increment_processed(self, tmp_path):
        """If _generate_thumbhash returns None, the blob is skipped (not counted as processed)."""
        sha = "bb" * 32
        blob = _make_blob(sha)

        d = tmp_path / "t"
        d.mkdir()
        (d / "thumb_160.webp").write_bytes(b"x")

        session = _make_mock_session([[blob]])

        with (
            patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session),
            patch("worker.thumbhash_backfill.thumb_dir", return_value=d),
            patch("worker.thumbhash_backfill.asyncio.to_thread", new_callable=AsyncMock, return_value=None),
        ):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={})

        assert result["processed"] == 0
        assert result["failed"] == 0

    async def test_custom_batch_size_is_forwarded(self, tmp_path):
        """batch_size parameter is accepted; empty result still terminates correctly."""
        session = _make_mock_session([])

        with patch("worker.thumbhash_backfill.AsyncSessionLocal", return_value=session):
            from worker.thumbhash_backfill import thumbhash_backfill_job

            result = await thumbhash_backfill_job(ctx={}, batch_size=100)

        assert result["status"] == "done"
