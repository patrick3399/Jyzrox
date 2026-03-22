"""
Tests for worker/scan.py — rescan_library_job, rescan_gallery_job,
auto_discover_job, scheduled_scan_job, and rescan_by_path_job.

Strategy: Mock-DB pattern (patch worker.scan.AsyncSessionLocal).
Redis is provided via ctx["redis"] as an AsyncMock.
Filesystem operations are mocked via patch on resolve_blob_path / thumb_dir.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_redis() -> AsyncMock:
    """Return a fully-wired mock Redis compatible with worker.scan usage."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    return r


def _make_blob(sha: str = "abc123", ext: str = ".jpg", storage: str = "cas") -> MagicMock:
    blob = MagicMock()
    blob.sha256 = sha
    blob.extension = ext
    blob.storage = storage
    blob.external_path = None
    return blob


def _make_image(
    image_id: int = 1,
    gallery_id: int = 10,
    page_num: int = 1,
    blob: MagicMock | None = None,
) -> MagicMock:
    img = MagicMock()
    img.id = image_id
    img.gallery_id = gallery_id
    img.page_num = page_num
    img.filename = f"page_{page_num:03d}.jpg"
    img.blob_sha256 = blob.sha256 if blob else None
    img.blob = blob
    return img


def _make_gallery(
    gallery_id: int = 10,
    source: str = "ehentai",
    source_id: str = "123",
    download_status: str = "complete",
    import_mode: str = "cas",
    pages: int = 5,
    library_path: str | None = None,
) -> MagicMock:
    g = MagicMock()
    g.id = gallery_id
    g.source = source
    g.source_id = source_id
    g.download_status = download_status
    g.import_mode = import_mode
    g.pages = pages
    g.library_path = library_path
    g.last_scanned_at = None
    return g


def _make_session(
    gallery_ids: list[int] | None = None,
    galleries: list[MagicMock] | None = None,
    images: list[MagicMock] | None = None,
    gallery_get_result: MagicMock | None = None,
) -> MagicMock:
    """
    Build a mock async SQLAlchemy session that can be used as an async
    context manager and satisfies the execute/scalars/all pattern.
    """
    session = AsyncMock()

    # Support session.get(Gallery, id) for rescan_gallery_job
    session.get = AsyncMock(return_value=gallery_get_result)

    # Build a flexible execute side_effect sequence.
    # The default returns empty results; callers override as needed.
    _ids_result = MagicMock()
    _ids_result.scalars.return_value.all.return_value = gallery_ids or []

    _imgs_result = MagicMock()
    _imgs_result.scalars.return_value.all.return_value = images or []

    _gals_result = MagicMock()
    _gals_result.scalars.return_value.all.return_value = galleries or []

    # Default: cycle through (ids, images, galleries) — tests can override
    session.execute = AsyncMock(
        side_effect=[_ids_result, _imgs_result, _gals_result] + [_imgs_result] * 10  # enough for repeated calls
    )

    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# TestRescanLibraryJob
# ---------------------------------------------------------------------------


class TestRescanLibraryJob:
    """Tests for rescan_library_job(ctx)."""

    async def test_empty_library_returns_total_zero(self):
        """Empty DB (no galleries) should return total=0 without errors."""
        from worker.scan import rescan_library_job

        session = _make_session(gallery_ids=[], galleries=[], images=[])
        r = _make_redis()

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("core.watcher.watcher_instance", None),
        ):
            result = await rescan_library_job({"redis": r})

        assert result["total"] == 0
        assert result["status"] == "done"

    async def test_missing_blob_files_removes_image_records(self):
        """Images whose blob files are missing on disk should be deleted."""
        from worker.scan import rescan_library_job

        blob = _make_blob(sha="deadbeef")
        img = _make_image(image_id=1, gallery_id=10, blob=blob)
        gallery = _make_gallery(gallery_id=10, pages=1)

        # ids result → images result → galleries result
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ids_res = MagicMock()
        ids_res.scalars.return_value.all.return_value = [10]

        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]

        gals_res = MagicMock()
        gals_res.scalars.return_value.all.return_value = [gallery]

        session.execute = AsyncMock(side_effect=[ids_res, imgs_res, gals_res, MagicMock(), MagicMock()])

        r = _make_redis()

        missing_path = MagicMock(spec=Path)
        missing_path.exists.return_value = False

        thumb_path = MagicMock(spec=Path)
        thumb_path.exists.return_value = False
        thumb_path.__truediv__ = lambda self, other: MagicMock(exists=MagicMock(return_value=False))

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=missing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("core.watcher.watcher_instance", None),
        ):
            result = await rescan_library_job({"redis": r})

        assert result["status"] == "done"
        # Confirm at least one execute call used a DELETE statement (batch image removal).
        # The batch delete is issued via sqlalchemy text(); check via the raw SQL string.
        all_executed = session.execute.call_args_list
        delete_calls = [c for c in all_executed if c.args and "DELETE" in str(c.args[0]).upper()]
        assert delete_calls, "Expected a batch DELETE execute call for missing images"

    async def test_gallery_with_zero_pages_marked_missing(self):
        """Gallery with 0 remaining pages (non-link mode) → download_status='missing'."""
        from worker.scan import rescan_library_job

        blob = _make_blob(sha="sha_zero")
        img = _make_image(image_id=2, gallery_id=20, blob=blob)
        gallery = _make_gallery(gallery_id=20, pages=1, import_mode="cas")

        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ids_res = MagicMock()
        ids_res.scalars.return_value.all.return_value = [20]
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]
        gals_res = MagicMock()
        gals_res.scalars.return_value.all.return_value = [gallery]

        session.execute = AsyncMock(side_effect=[ids_res, imgs_res, gals_res, MagicMock(), MagicMock()])

        r = _make_redis()
        missing_path = MagicMock(spec=Path)
        missing_path.exists.return_value = False
        thumb_path = MagicMock(spec=Path)
        thumb_path.exists.return_value = False
        thumb_path.__truediv__ = lambda self, other: MagicMock(exists=MagicMock(return_value=False))

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=missing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("core.watcher.watcher_instance", None),
        ):
            await rescan_library_job({"redis": r})

        assert gallery.download_status == "missing"

    async def test_cancel_signal_respected(self):
        """Cancel signal (b'cancel' in Redis) should stop processing and return 'cancelled'."""
        from worker.scan import rescan_library_job

        gallery = _make_gallery(gallery_id=30)

        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ids_res = MagicMock()
        ids_res.scalars.return_value.all.return_value = [30]
        session.execute = AsyncMock(return_value=ids_res)

        r = _make_redis()
        # Simulate cancel flag already set before first chunk
        r.get = AsyncMock(return_value=b"cancel")

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("core.watcher.watcher_instance", None),
        ):
            result = await rescan_library_job({"redis": r})

        assert result["status"] == "cancelled"
        r.delete.assert_awaited_with("rescan:cancel")
        # Progress key should be set with cancelled status
        setex_calls = [str(c) for c in r.setex.call_args_list]
        assert any("cancelled" in c for c in setex_calls)

    async def test_progress_written_to_redis(self):
        """Progress should be written to 'rescan:progress' key during scan."""
        from worker.scan import rescan_library_job

        session = _make_session(gallery_ids=[], galleries=[], images=[])
        r = _make_redis()

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("core.watcher.watcher_instance", None),
        ):
            await rescan_library_job({"redis": r})

        # setex called for progress key (even with 0 galleries — done status)
        r.setex.assert_awaited()
        key_args = [c.args[0] for c in r.setex.call_args_list]
        assert "rescan:progress" in key_args

    async def test_thumbnails_enqueued_for_images_missing_thumbs(self):
        """Galleries with images lacking thumb_160.webp should enqueue thumbnail_job."""
        from worker.scan import rescan_library_job

        blob = _make_blob(sha="thumbsha")
        img = _make_image(image_id=3, gallery_id=40, blob=blob)
        gallery = _make_gallery(gallery_id=40, pages=1)

        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ids_res = MagicMock()
        ids_res.scalars.return_value.all.return_value = [40]
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]
        gals_res = MagicMock()
        gals_res.scalars.return_value.all.return_value = [gallery]

        session.execute = AsyncMock(side_effect=[ids_res, imgs_res, gals_res])

        r = _make_redis()

        # File exists — so image is not removed
        existing_path = MagicMock(spec=Path)
        existing_path.exists.return_value = True

        # Thumb dir exists but thumb_160.webp does NOT → missing_thumb = True
        thumb_160 = MagicMock(spec=Path)
        thumb_160.exists.return_value = False
        thumb_path = MagicMock(spec=Path)
        thumb_path.__truediv__ = lambda self, other: thumb_160

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=existing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("core.watcher.watcher_instance", None),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            await rescan_library_job({"redis": r})

        mock_enqueue.assert_awaited_with("thumbnail_job", gallery_id=40)

    async def test_watcher_paused_and_resumed(self):
        """Watcher should be paused at the start and resumed at the end."""
        from worker.scan import rescan_library_job

        session = _make_session(gallery_ids=[], galleries=[], images=[])
        r = _make_redis()

        mock_watcher = MagicMock()
        mock_watcher.is_running = True
        mock_watcher.pause = MagicMock()
        mock_watcher.resume = MagicMock()

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("core.watcher.watcher_instance", mock_watcher),
            # The job imports watcher_instance inside the function body
            patch("worker.scan.__builtins__", __builtins__),
        ):
            # Patch the import inside the function
            import core.watcher as _cw

            original = _cw.watcher_instance
            _cw.watcher_instance = mock_watcher
            try:
                await rescan_library_job({"redis": r})
            finally:
                _cw.watcher_instance = original

        mock_watcher.pause.assert_called_once()
        mock_watcher.resume.assert_called_once()

    async def test_no_thumbnail_enqueue_when_thumbs_present(self):
        """No thumbnail_job should be enqueued when all thumbnails already exist."""
        from worker.scan import rescan_library_job

        blob = _make_blob(sha="hasthumb")
        img = _make_image(image_id=5, gallery_id=50, blob=blob)
        gallery = _make_gallery(gallery_id=50, pages=1)

        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ids_res = MagicMock()
        ids_res.scalars.return_value.all.return_value = [50]
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]
        gals_res = MagicMock()
        gals_res.scalars.return_value.all.return_value = [gallery]

        session.execute = AsyncMock(side_effect=[ids_res, imgs_res, gals_res])

        r = _make_redis()

        existing_path = MagicMock(spec=Path)
        existing_path.exists.return_value = True

        thumb_160 = MagicMock(spec=Path)
        thumb_160.exists.return_value = True  # thumb IS present
        thumb_path = MagicMock(spec=Path)
        thumb_path.__truediv__ = lambda self, other: thumb_160

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=existing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("core.watcher.watcher_instance", None),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            await rescan_library_job({"redis": r})

        mock_enqueue.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestRescanGalleryJob
# ---------------------------------------------------------------------------


class TestRescanGalleryJob:
    """Tests for rescan_gallery_job(ctx, gallery_id)."""

    async def test_gallery_not_found_returns_failed(self):
        """gallery_id that does not exist should return status='failed'."""
        from worker.scan import rescan_gallery_job

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        r = _make_redis()

        with patch("worker.scan.AsyncSessionLocal", return_value=session):
            result = await rescan_gallery_job({"redis": r}, gallery_id=999)

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    async def test_missing_images_removed_from_db(self):
        """Images whose blob files are missing should be deleted from the session."""
        from worker.scan import rescan_gallery_job

        blob = _make_blob(sha="missingsha")
        img = _make_image(image_id=10, gallery_id=100, blob=blob)
        gallery = _make_gallery(gallery_id=100, pages=1)

        session = AsyncMock()
        session.get = AsyncMock(return_value=gallery)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        # execute returns: excluded_blobs, images (step1), surviving_images, final_images
        excl_res = MagicMock()
        excl_res.scalars.return_value.all.return_value = []
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]
        surv_res = MagicMock()
        surv_res.scalars.return_value.all.return_value = []
        final_res = MagicMock()
        final_res.scalars.return_value.all.return_value = []

        session.execute = AsyncMock(side_effect=[excl_res, imgs_res, surv_res, final_res])

        r = _make_redis()

        missing_path = MagicMock(spec=Path)
        missing_path.exists.return_value = False
        thumb_path = MagicMock(spec=Path)
        thumb_path.exists.return_value = False
        thumb_path.__truediv__ = lambda self, other: MagicMock(exists=MagicMock(return_value=False))

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=missing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("worker.scan.decrement_ref_count", new_callable=AsyncMock),
            patch("worker.scan.library_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await rescan_gallery_job({"redis": r}, gallery_id=100)

        session.delete.assert_awaited_with(img)
        assert result["removed"] == 1

    async def test_new_files_discovered_and_added(self):
        """New image files on disk should be added to the DB."""
        from worker.scan import rescan_gallery_job

        gallery = _make_gallery(gallery_id=200, pages=0, download_status="missing")

        session = AsyncMock()
        session.get = AsyncMock(return_value=gallery)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        excl_res = MagicMock()
        excl_res.scalars.return_value.all.return_value = []
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = []  # no existing images
        surv_res = MagicMock()
        surv_res.scalars.return_value.all.return_value = []
        final_res = MagicMock()
        # final count after insert
        final_img = _make_image(image_id=20, gallery_id=200)
        final_res.scalars.return_value.all.return_value = [final_img]

        # pg_insert result (on_conflict_do_nothing) — scalar_one_or_none returns
        # a row, triggering an UPDATE for the blob's ref_count
        insert_exec_res = MagicMock()
        update_ref_res = MagicMock()

        session.execute = AsyncMock(
            side_effect=[excl_res, imgs_res, surv_res, insert_exec_res, update_ref_res, final_res]
        )

        r = _make_redis()

        # Create a real temp file to iterate over
        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            new_file = pathlib.Path(tmpdir) / "001.jpg"
            new_file.write_bytes(b"fake_image_data")

            fake_gallery_dir = MagicMock(spec=Path)
            fake_gallery_dir.exists.return_value = True
            fake_gallery_dir.is_dir.return_value = True
            fake_gallery_dir.iterdir.return_value = [new_file]

            mock_blob = _make_blob(sha="newfilesha")

            with (
                patch("worker.scan.AsyncSessionLocal", return_value=session),
                patch("worker.scan.library_dir", return_value=fake_gallery_dir),
                patch("worker.scan._sha256", return_value="newfilesha"),
                patch("worker.scan.store_blob", new_callable=AsyncMock, return_value=mock_blob),
                patch("worker.scan.create_library_symlink", new_callable=AsyncMock),
                patch("worker.scan.decrement_ref_count", new_callable=AsyncMock),
            ):
                result = await rescan_gallery_job({"redis": r}, gallery_id=200)

        assert result["added"] == 1
        assert result["status"] == "done"

    async def test_excluded_blobs_skipped(self):
        """Files whose sha256 is in the excluded_blobs set should be skipped."""
        from worker.scan import rescan_gallery_job

        gallery = _make_gallery(gallery_id=300, pages=0)

        session = AsyncMock()
        session.get = AsyncMock(return_value=gallery)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        excl_res = MagicMock()
        excl_res.scalars.return_value.all.return_value = ["excludedsha"]
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = []
        surv_res = MagicMock()
        surv_res.scalars.return_value.all.return_value = []
        final_res = MagicMock()
        final_res.scalars.return_value.all.return_value = []

        session.execute = AsyncMock(side_effect=[excl_res, imgs_res, surv_res, final_res])

        r = _make_redis()

        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            excl_file = pathlib.Path(tmpdir) / "excluded.jpg"
            excl_file.write_bytes(b"data")

            fake_gallery_dir = MagicMock(spec=Path)
            fake_gallery_dir.exists.return_value = True
            fake_gallery_dir.is_dir.return_value = True
            fake_gallery_dir.iterdir.return_value = [excl_file]

            store_blob_mock = AsyncMock()

            with (
                patch("worker.scan.AsyncSessionLocal", return_value=session),
                patch("worker.scan.library_dir", return_value=fake_gallery_dir),
                patch("worker.scan._sha256", return_value="excludedsha"),
                patch("worker.scan.store_blob", store_blob_mock),
                patch("worker.scan.decrement_ref_count", new_callable=AsyncMock),
            ):
                result = await rescan_gallery_job({"redis": r}, gallery_id=300)

        # store_blob should NOT have been called since the file is excluded
        store_blob_mock.assert_not_awaited()
        assert result["added"] == 0

    async def test_status_transitions_missing_to_complete_when_files_found(self):
        """Gallery with download_status='missing' should become 'complete' when files are found."""
        from worker.scan import rescan_gallery_job

        gallery = _make_gallery(gallery_id=400, pages=0, download_status="missing")

        session = AsyncMock()
        session.get = AsyncMock(return_value=gallery)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        blob = _make_blob(sha="foundsha")
        existing_img = _make_image(image_id=30, gallery_id=400, blob=blob)

        excl_res = MagicMock()
        excl_res.scalars.return_value.all.return_value = []
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [existing_img]
        surv_res = MagicMock()
        surv_res.scalars.return_value.all.return_value = [existing_img]
        final_res = MagicMock()
        final_res.scalars.return_value.all.return_value = [existing_img]

        session.execute = AsyncMock(side_effect=[excl_res, imgs_res, surv_res, final_res])

        r = _make_redis()

        existing_path = MagicMock(spec=Path)
        existing_path.exists.return_value = True
        thumb_160 = MagicMock(spec=Path)
        thumb_160.exists.return_value = True
        thumb_path = MagicMock(spec=Path)
        thumb_path.__truediv__ = lambda self, other: thumb_160

        fake_gallery_dir = MagicMock(spec=Path)
        fake_gallery_dir.exists.return_value = True
        fake_gallery_dir.is_dir.return_value = True
        fake_gallery_dir.iterdir.return_value = []  # no new files on disk

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=existing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("worker.scan.library_dir", return_value=fake_gallery_dir),
            patch("worker.scan.decrement_ref_count", new_callable=AsyncMock),
        ):
            result = await rescan_gallery_job({"redis": r}, gallery_id=400)

        assert gallery.download_status == "complete"
        assert result["status"] == "done"
        assert result["pages"] == 1

    async def test_zero_pages_non_link_mode_marks_missing(self):
        """Gallery with 0 pages and import_mode != 'link' should be marked 'missing'."""
        from worker.scan import rescan_gallery_job

        gallery = _make_gallery(gallery_id=500, pages=1, download_status="complete", import_mode="cas")

        session = AsyncMock()
        session.get = AsyncMock(return_value=gallery)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        blob = _make_blob(sha="lostsha")
        img = _make_image(image_id=40, gallery_id=500, blob=blob)

        excl_res = MagicMock()
        excl_res.scalars.return_value.all.return_value = []
        imgs_res = MagicMock()
        imgs_res.scalars.return_value.all.return_value = [img]
        surv_res = MagicMock()
        surv_res.scalars.return_value.all.return_value = []
        final_res = MagicMock()
        final_res.scalars.return_value.all.return_value = []

        session.execute = AsyncMock(side_effect=[excl_res, imgs_res, surv_res, final_res])

        r = _make_redis()

        missing_path = MagicMock(spec=Path)
        missing_path.exists.return_value = False
        thumb_path = MagicMock(spec=Path)
        thumb_path.exists.return_value = False
        thumb_path.__truediv__ = lambda self, other: MagicMock(exists=MagicMock(return_value=False))

        fake_gallery_dir = MagicMock(spec=Path)
        fake_gallery_dir.exists.return_value = False

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.resolve_blob_path", return_value=missing_path),
            patch("worker.scan.thumb_dir", return_value=thumb_path),
            patch("worker.scan.library_dir", return_value=fake_gallery_dir),
            patch("worker.scan.decrement_ref_count", new_callable=AsyncMock),
        ):
            result = await rescan_gallery_job({"redis": r}, gallery_id=500)

        assert gallery.download_status == "missing"


# ---------------------------------------------------------------------------
# TestAutoDiscoverJob
# ---------------------------------------------------------------------------


class TestAutoDiscoverJob:
    """Tests for auto_discover_job(ctx)."""

    async def test_empty_library_paths_returns_zero_discovered(self):
        """No library paths configured → discovered=0 without errors."""
        from worker.scan import auto_discover_job

        session = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        existing_res = MagicMock()
        existing_res.all.return_value = []
        session.execute = AsyncMock(return_value=existing_res)

        r = _make_redis()

        with (
            patch("worker.scan.get_all_library_paths", new_callable=AsyncMock, return_value=[]),
            patch("worker.scan.AsyncSessionLocal", return_value=session),
        ):
            result = await auto_discover_job({"redis": r})

        assert result["discovered"] == 0

    async def test_hidden_directories_skipped(self):
        """Directories beginning with '.' should not produce gallery candidates."""
        from worker.scan import auto_discover_job

        session = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        existing_res = MagicMock()
        existing_res.all.return_value = []
        session.execute = AsyncMock(return_value=existing_res)

        r = _make_redis()

        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            hidden_dir = pathlib.Path(tmpdir) / ".hidden_gallery"
            hidden_dir.mkdir()
            (hidden_dir / "image.jpg").write_bytes(b"data")

            with (
                patch("worker.scan.get_all_library_paths", new_callable=AsyncMock, return_value=[tmpdir]),
                patch("worker.scan.AsyncSessionLocal", return_value=session),
            ):
                result = await auto_discover_job({"redis": r})

        assert result["discovered"] == 0

    async def test_existing_galleries_not_recreated(self):
        """Directories already in the DB should be skipped (no duplicate INSERT)."""
        from worker.scan import auto_discover_job

        session = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        r = _make_redis()

        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            gallery_dir = pathlib.Path(tmpdir) / "my_gallery"
            gallery_dir.mkdir()
            (gallery_dir / "image.jpg").write_bytes(b"data")

            # Simulate existing entry: (source_id="my_gallery", library_path=tmpdir)
            existing_row = MagicMock()
            existing_row.source_id = "my_gallery"
            existing_row.library_path = tmpdir
            existing_res = MagicMock()
            existing_res.all.return_value = [existing_row]
            session.execute = AsyncMock(return_value=existing_res)

            with (
                patch("worker.scan.get_all_library_paths", new_callable=AsyncMock, return_value=[tmpdir]),
                patch("worker.scan.AsyncSessionLocal", return_value=session),
            ):
                result = await auto_discover_job({"redis": r})

        assert result["discovered"] == 0

    async def test_new_gallery_directories_discovered_and_created(self):
        """New directory with media files should trigger INSERT and enqueue_job."""
        from worker.scan import auto_discover_job

        session = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        r = _make_redis()

        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            gallery_dir = pathlib.Path(tmpdir) / "new_gallery"
            gallery_dir.mkdir()
            (gallery_dir / "image.jpg").write_bytes(b"data")

            # No existing galleries
            existing_res = MagicMock()
            existing_res.all.return_value = []
            # INSERT RETURNING id result
            insert_res = MagicMock()
            insert_res.scalar_one_or_none.return_value = 99

            session.execute = AsyncMock(side_effect=[existing_res, insert_res])

            with (
                patch("worker.scan.get_all_library_paths", new_callable=AsyncMock, return_value=[tmpdir]),
                patch("worker.scan.AsyncSessionLocal", return_value=session),
                patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
            ):
                result = await auto_discover_job({"redis": r})

        assert result["discovered"] == 1
        mock_enqueue.assert_awaited_once()
        enqueue_kwargs = mock_enqueue.call_args.kwargs
        assert mock_enqueue.call_args.args[0] == "local_import_job"

    async def test_only_directories_with_supported_extensions_counted(self):
        """Directory containing only unsupported file types should not create a gallery."""
        from worker.scan import auto_discover_job

        session = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        existing_res = MagicMock()
        existing_res.all.return_value = []
        session.execute = AsyncMock(return_value=existing_res)

        r = _make_redis()

        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmpdir:
            gallery_dir = pathlib.Path(tmpdir) / "text_only"
            gallery_dir.mkdir()
            (gallery_dir / "readme.txt").write_bytes(b"text")
            (gallery_dir / "data.csv").write_bytes(b"csv")

            with (
                patch("worker.scan.get_all_library_paths", new_callable=AsyncMock, return_value=[tmpdir]),
                patch("worker.scan.AsyncSessionLocal", return_value=session),
            ):
                result = await auto_discover_job({"redis": r})

        assert result["discovered"] == 0


# ---------------------------------------------------------------------------
# TestScheduledScanJob
# ---------------------------------------------------------------------------


class TestScheduledScanJob:
    """Tests for scheduled_scan_job(ctx)."""

    async def test_cron_not_reached_returns_skipped(self):
        """Should return {'status': 'skipped'} when _cron_should_run is False."""
        from worker.scan import scheduled_scan_job

        r = _make_redis()

        with patch("worker.scan._cron_should_run", new_callable=AsyncMock, return_value=False):
            result = await scheduled_scan_job({"redis": r})

        assert result["status"] == "skipped"

    async def test_normal_trigger_calls_discover_and_rescan(self):
        """When cron fires, both auto_discover_job and rescan_library_job are called."""
        from worker.scan import scheduled_scan_job

        r = _make_redis()

        auto_discover_mock = AsyncMock(return_value={"discovered": 0})
        rescan_mock = AsyncMock(return_value={"status": "done", "total": 0})

        with (
            patch("worker.scan._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.scan._cron_record", new_callable=AsyncMock),
            patch("worker.scan.auto_discover_job", auto_discover_mock),
            patch("worker.scan.rescan_library_job", rescan_mock),
        ):
            result = await scheduled_scan_job({"redis": r})

        assert result["status"] == "done"
        auto_discover_mock.assert_awaited_once()
        rescan_mock.assert_awaited_once()

    async def test_records_cron_execution(self):
        """_cron_record should be called to record the scan outcome."""
        from worker.scan import scheduled_scan_job

        r = _make_redis()
        cron_record_mock = AsyncMock()

        with (
            patch("worker.scan._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.scan._cron_record", cron_record_mock),
            patch("worker.scan.auto_discover_job", new_callable=AsyncMock, return_value={"discovered": 0}),
            patch(
                "worker.scan.rescan_library_job", new_callable=AsyncMock, return_value={"status": "done", "total": 0}
            ),
        ):
            await scheduled_scan_job({"redis": r})

        # Should have been called at least twice: once for "running", once for "ok"
        assert cron_record_mock.await_count >= 2
        record_statuses = [c.args[2] for c in cron_record_mock.call_args_list]
        assert "running" in record_statuses
        assert "ok" in record_statuses


# ---------------------------------------------------------------------------
# TestRescanByPathJob
# ---------------------------------------------------------------------------


class TestRescanByPathJob:
    """Tests for rescan_by_path_job(ctx, dir_path)."""

    async def test_no_matching_gallery_returns_no_gallery_found(self):
        """A path that matches no gallery triggers auto_discover and returns no_gallery_found."""
        from worker.scan import rescan_by_path_job

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        none_res = MagicMock()
        none_res.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=none_res)

        r = _make_redis()

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.settings") as mock_settings,
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            mock_settings.data_library_path = "/data/library"
            result = await rescan_by_path_job({"redis": r}, dir_path="/some/external/path")

        assert result["status"] == "no_gallery_found"
        mock_enqueue.assert_awaited_with("auto_discover_job")

    async def test_gallery_found_by_library_path_delegates_to_rescan_gallery(self):
        """Path under data_library_path resolves gallery and delegates to rescan_gallery_job."""
        from worker.scan import rescan_by_path_job

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        found_res = MagicMock()
        found_res.scalar_one_or_none.return_value = 77
        session.execute = AsyncMock(return_value=found_res)

        r = _make_redis()
        rescan_gallery_mock = AsyncMock(return_value={"status": "done", "gallery_id": 77})

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.settings") as mock_settings,
            patch("worker.scan.rescan_gallery_job", rescan_gallery_mock),
        ):
            mock_settings.data_library_path = "/data/library"
            result = await rescan_by_path_job({"redis": r}, dir_path="/data/library/ehentai/12345")

        rescan_gallery_mock.assert_awaited_once_with({"redis": r}, 77)
        assert result["status"] == "done"

    async def test_gallery_found_by_blob_external_path(self):
        """Path not under library base falls back to blob external_path lookup."""
        from worker.scan import rescan_by_path_job

        # The path is NOT under lib_base so the library lookup block is skipped
        # entirely (ValueError from relative_to).  Only ONE AsyncSessionLocal call
        # is made — the blob external_path lookup — which returns gallery_id 88.
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        found_res = MagicMock()
        found_res.scalar_one_or_none.return_value = 88
        session.execute = AsyncMock(return_value=found_res)

        r = _make_redis()
        rescan_gallery_mock = AsyncMock(return_value={"status": "done", "gallery_id": 88})

        with (
            patch("worker.scan.AsyncSessionLocal", return_value=session),
            patch("worker.scan.settings") as mock_settings,
            patch("worker.scan.rescan_gallery_job", rescan_gallery_mock),
        ):
            mock_settings.data_library_path = "/data/library"
            result = await rescan_by_path_job({"redis": r}, dir_path="/mnt/nas/manga_collection")

        rescan_gallery_mock.assert_awaited_once_with({"redis": r}, 88)
        assert result["status"] == "done"
