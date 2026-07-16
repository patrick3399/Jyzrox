"""
Unit tests for worker.progressive.ProgressiveImporter.

Strategy:
- Patch worker.progressive.AsyncSessionLocal with the test session factory so
  all DB calls use the SQLite in-memory DB.
- Insert Gallery / Blob / Image records directly via raw SQL (SQLite-compatible)
  to avoid pg_insert / on_conflict usage in the test setup.
- Mock filesystem helpers (library_dir, thumb_dir) where filesystem interaction
  is needed; use tmp_path to create real directories for removal tests.
- Mock settings.tag_model_enabled=False to prevent tagger job enqueue in finalize().
"""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers — insert records via raw SQL (SQLite-compatible, no pg_insert)
# ---------------------------------------------------------------------------


async def _insert_gallery(
    db_session,
    source: str = "test_source",
    source_id: str = "test_001",
    title: str = "Test Gallery",
    download_status: str = "downloading",
    pages: int = 0,
) -> int:
    """Insert a gallery row and return its integer id."""
    result = await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, download_status) "
            "VALUES (:source, :source_id, :title, :pages, :download_status) "
            "RETURNING id"
        ),
        {
            "source": source,
            "source_id": source_id,
            "title": title,
            "pages": pages,
            "download_status": download_status,
        },
    )
    await db_session.commit()
    row = result.fetchone()
    return row[0]


async def _insert_blob(
    db_session,
    sha256: str,
    ref_count: int = 1,
    extension: str = ".jpg",
) -> None:
    """Insert a blob row."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO blobs (sha256, file_size, extension, ref_count, storage) "
            "VALUES (:sha256, :file_size, :ext, :ref_count, 'cas')"
        ),
        {"sha256": sha256, "file_size": 1024, "ext": extension, "ref_count": ref_count},
    )
    await db_session.commit()


async def _insert_image(
    db_session,
    gallery_id: int,
    page_num: int,
    blob_sha256: str,
    filename: str = "img.jpg",
    visibility: str = "active",
    source_item_id: str | None = None,
) -> int:
    """Insert an image row and return its id."""
    result = await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, visibility, source_item_id) "
            "VALUES (:gid, :page_num, :filename, :sha, :visibility, :source_item_id) "
            "RETURNING id"
        ),
        {
            "gid": gallery_id,
            "page_num": page_num,
            "filename": filename,
            "sha": blob_sha256,
            "visibility": visibility,
            "source_item_id": source_item_id,
        },
    )
    await db_session.commit()
    row = result.fetchone()
    return row[0]


def _make_session_factory_cm(factory):
    """Wrap an async_sessionmaker so it works as an async context manager.

    ProgressiveImporter calls ``async with AsyncSessionLocal() as session:``.
    The test factory already supports this protocol, but we need to ensure
    each call opens a *new* session that shares the same SQLite connection
    so committed writes are visible across calls.
    """

    @asynccontextmanager
    async def _cm():
        async with factory() as session:
            yield session

    class _Factory:
        def __call__(self):
            return _cm()

    return _Factory()


# ---------------------------------------------------------------------------
# TestProgressiveImporterCleanup
# ---------------------------------------------------------------------------


class TestProgressiveImporterCleanup:
    """Tests for ProgressiveImporter.cleanup()."""

    async def test_cleanup_deletes_gallery_and_images(self, db_session, db_session_factory):
        """cleanup() must delete the gallery row and CASCADE-delete its images."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session)
        sha = "aabbcc" + "0" * 58
        await _insert_blob(db_session, sha)
        await _insert_image(db_session, gallery_id, 1, sha)
        await _insert_image(db_session, gallery_id, 2, sha)

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"

        fake_factory = _make_session_factory_cm(db_session_factory)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=Path("/nonexistent/lib")),
            patch("worker.progressive.thumb_dir", return_value=Path("/nonexistent/thumb")),
        ):
            await importer.cleanup()

        # Gallery must be gone
        row = (await db_session.execute(text("SELECT id FROM galleries WHERE id = :id"), {"id": gallery_id})).fetchone()
        assert row is None, "Gallery should have been deleted by cleanup()"

        # Images must be gone (CASCADE)
        count = (
            await db_session.execute(text("SELECT COUNT(*) FROM images WHERE gallery_id = :id"), {"id": gallery_id})
        ).scalar()
        assert count == 0, "Images should have been CASCADE-deleted with the gallery"

    async def test_cleanup_decrements_blob_ref_count(self, db_session, db_session_factory):
        """cleanup() must call decrement_ref_count for each blob linked to the gallery."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session)
        sha_a = "aaaaaa" + "0" * 58
        sha_b = "bbbbbb" + "0" * 58

        await _insert_blob(db_session, sha_a, ref_count=2)
        await _insert_blob(db_session, sha_b, ref_count=1)
        await _insert_image(db_session, gallery_id, 1, sha_a)
        await _insert_image(db_session, gallery_id, 2, sha_b)

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"

        fake_factory = _make_session_factory_cm(db_session_factory)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=Path("/nonexistent/lib")),
            patch("worker.progressive.thumb_dir", return_value=Path("/nonexistent/thumb")),
        ):
            await importer.cleanup()

        # sha_a: 2 - 1 = 1; sha_b: 1 - 1 = 0
        row_a = (
            await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256 = :sha"), {"sha": sha_a})
        ).fetchone()
        row_b = (
            await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256 = :sha"), {"sha": sha_b})
        ).fetchone()

        assert row_a[0] == 1, "sha_a ref_count should have been decremented from 2 to 1"
        assert row_b[0] == 0, "sha_b ref_count should have been decremented from 1 to 0"

    async def test_cleanup_removes_filesystem_artifacts(self, db_session, db_session_factory, tmp_path):
        """cleanup() must remove library_dir and thumb_dirs for zero-ref blobs."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session)
        sha = "cccccc" + "0" * 58
        # ref_count=1 so after decrement it becomes 0 — thumb dir should be removed
        await _insert_blob(db_session, sha, ref_count=1)
        await _insert_image(db_session, gallery_id, 1, sha)

        # Create real directories under tmp_path
        lib_dir = tmp_path / "library" / "test_source" / "test_001"
        lib_dir.mkdir(parents=True)
        (lib_dir / "img.jpg").write_bytes(b"fake")

        thumb_directory = tmp_path / "thumbs" / sha[:2] / sha[2:4] / sha
        thumb_directory.mkdir(parents=True)
        (thumb_directory / "thumb_160.webp").write_bytes(b"fake_thumb")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"

        fake_factory = _make_session_factory_cm(db_session_factory)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=lib_dir),
            patch("worker.progressive.thumb_dir", return_value=thumb_directory),
        ):
            await importer.cleanup()

        assert not lib_dir.exists(), "Library symlink directory should have been removed"
        assert not thumb_directory.exists(), "Thumbnail directory should have been removed for zero-ref blob"

    async def test_cleanup_no_gallery_is_noop(self, db_session, db_session_factory):
        """cleanup() with no gallery_id set must not raise any exception."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        # gallery_id is None — no setup needed

        fake_factory = _make_session_factory_cm(db_session_factory)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            # Must complete without raising
            await importer.cleanup()


# ---------------------------------------------------------------------------
# TestProgressiveImporterPreExistingCancel — edge case audit #53 / BR-001
# ---------------------------------------------------------------------------


class TestProgressiveImporterPreExistingCancel:
    """Audit #53: cancelling a run that attached to a pre-existing ACTIVE
    gallery must roll back only this run's additions — never delete the
    gallery, its prior images, or demote its download_status."""

    async def _attach_importer(
        self, db_session, db_session_factory, gallery_id, source="test_source", source_id="test_001"
    ):
        """Simulate the ensure_gallery attach flow for a pre-existing gallery:
        trashed-conflict inspection (which snapshots the existing row), then
        gallery state load (which records pre-existing image ids)."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.source = source
        importer.source_id = source_id

        fake_factory = _make_session_factory_cm(db_session_factory)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            trashed = await importer._detect_trashed_conflict(db_session, source, source_id)
            assert trashed is None
            importer.gallery_id = gallery_id
            await importer._load_gallery_state()
        return importer

    async def test_cancel_redownload_of_existing_active_gallery_preserves_gallery_and_images(
        self, db_session, db_session_factory, tmp_path
    ):
        """Cancel of a re-download must delete only images added by this run,
        keep the gallery row and prior images/symlinks, and restore the
        previous download_status."""
        gallery_id = await _insert_gallery(db_session, download_status="complete", pages=2)
        sha_old1 = "aaaa01" + "0" * 58
        sha_old2 = "aaaa02" + "0" * 58
        sha_new = "bbbb01" + "0" * 58
        await _insert_blob(db_session, sha_old1, ref_count=1)
        await _insert_blob(db_session, sha_old2, ref_count=1)
        await _insert_blob(db_session, sha_new, ref_count=1)
        img_old1 = await _insert_image(db_session, gallery_id, 1, sha_old1, filename="001.jpg")
        img_old2 = await _insert_image(db_session, gallery_id, 2, sha_old2, filename="002.jpg")

        importer = await self._attach_importer(db_session, db_session_factory, gallery_id)
        assert importer.pre_existing is True

        # This run imports one new page before the user cancels
        await _insert_image(db_session, gallery_id, 3, sha_new, filename="003.jpg")

        lib_dir = tmp_path / "library" / "test_source" / "test_001"
        lib_dir.mkdir(parents=True)
        for name in ("001.jpg", "002.jpg", "003.jpg"):
            (lib_dir / name).write_bytes(b"fake")
        thumb_directory = tmp_path / "thumbs" / sha_new[:2] / sha_new[2:4] / sha_new
        thumb_directory.mkdir(parents=True)
        (thumb_directory / "thumb_160.webp").write_bytes(b"fake_thumb")

        fake_factory = _make_session_factory_cm(db_session_factory)
        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=lib_dir),
            patch("worker.progressive.thumb_dir", return_value=thumb_directory),
        ):
            await importer.cleanup()

        row = (
            await db_session.execute(
                text("SELECT download_status, pages FROM galleries WHERE id = :id"), {"id": gallery_id}
            )
        ).fetchone()
        assert row is not None, "pre-existing gallery must not be deleted on cancel"
        assert row[0] == "complete", "previous download_status must be restored"
        assert row[1] == 2, "pages must be restored to the pre-run image count"

        remaining = {
            r[0]
            for r in (
                await db_session.execute(text("SELECT id FROM images WHERE gallery_id = :id"), {"id": gallery_id})
            ).fetchall()
        }
        assert remaining == {img_old1, img_old2}, "only images added by this run may be removed"

        for sha, expected in ((sha_old1, 1), (sha_old2, 1), (sha_new, 0)):
            ref = (
                await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256 = :sha"), {"sha": sha})
            ).fetchone()[0]
            assert ref == expected, f"blob {sha[:6]} ref_count should be {expected}"

        assert (lib_dir / "001.jpg").exists(), "pre-existing symlinks must survive"
        assert (lib_dir / "002.jpg").exists(), "pre-existing symlinks must survive"
        assert not (lib_dir / "003.jpg").exists(), "this run's symlink must be removed"
        assert lib_dir.exists(), "library dir of a pre-existing gallery must not be rmtree'd"
        assert not thumb_directory.exists(), "thumb dir of the now-unreferenced new blob must be removed"

    async def test_cancel_fresh_download_still_fully_deletes_gallery(self, db_session, db_session_factory):
        """Regression guard: full-delete behavior must survive for galleries
        created by this run (pre_existing stays False)."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        trashed = await importer._detect_trashed_conflict(db_session, "test_source", "fresh_001")
        assert trashed is None
        assert importer.pre_existing is False, "no gallery existed, so this run is not pre-existing"

        gallery_id = await _insert_gallery(db_session, source_id="fresh_001")
        sha = "cccc01" + "0" * 58
        await _insert_blob(db_session, sha, ref_count=1)
        await _insert_image(db_session, gallery_id, 1, sha)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "fresh_001"

        fake_factory = _make_session_factory_cm(db_session_factory)
        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=Path("/nonexistent/lib")),
            patch("worker.progressive.thumb_dir", return_value=Path("/nonexistent/thumb")),
        ):
            await importer.cleanup()

        row = (await db_session.execute(text("SELECT id FROM galleries WHERE id = :id"), {"id": gallery_id})).fetchone()
        assert row is None, "a gallery created by this run must still be fully deleted on cancel"

    async def test_abort_of_zero_new_image_refresh_does_not_demote_complete_status(
        self, db_session, db_session_factory
    ):
        """abort() on a pre-existing complete gallery whose run imported nothing
        new must restore 'complete', not force 'partial'."""
        gallery_id = await _insert_gallery(db_session, download_status="complete", pages=2)
        sha_a = "dddd01" + "0" * 58
        sha_b = "dddd02" + "0" * 58
        await _insert_blob(db_session, sha_a)
        await _insert_blob(db_session, sha_b)
        await _insert_image(db_session, gallery_id, 1, sha_a)
        await _insert_image(db_session, gallery_id, 2, sha_b)

        importer = await self._attach_importer(db_session, db_session_factory, gallery_id)

        fake_factory = _make_session_factory_cm(db_session_factory)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer.abort()

        status = (
            await db_session.execute(text("SELECT download_status FROM galleries WHERE id = :id"), {"id": gallery_id})
        ).fetchone()[0]
        assert status == "complete", "a refresh that added nothing must not demote complete → partial"


# ---------------------------------------------------------------------------
# TestProgressiveImporterTrashedGuard — edge case audit #8
# ---------------------------------------------------------------------------


class TestProgressiveImporterTrashedGuard:
    """Re-downloading / re-importing a trashed gallery must not mutate or
    resurrect it (audit #8; same invariant as rescan #58 / BE-T16)."""

    async def test_ensure_gallery_from_import_data_into_trashed_gallery_does_not_mutate(
        self, db_session, db_session_factory
    ):
        """An upsert targeting a trashed gallery must skip without mutating it."""
        from plugins.models import GalleryImportData
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(
            db_session,
            source="trash_src",
            source_id="trash_001",
            title="Original Title",
            download_status="complete",
            pages=5,
        )
        # Send it to trash.
        await db_session.execute(
            text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :gid"),
            {"gid": gallery_id},
        )
        await db_session.commit()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        data = GalleryImportData(
            source="trash_src",
            source_id="trash_001",
            title="New Title From Redownload",
            tags=["should", "not", "apply"],
        )

        fake_factory = _make_session_factory_cm(db_session_factory)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            returned_id = await importer.ensure_gallery_from_import_data(data)

        assert returned_id == gallery_id
        assert importer.skipped_trashed is True

        row = (
            await db_session.execute(
                text("SELECT title, download_status, pages, deleted_at FROM galleries WHERE id = :gid"),
                {"gid": gallery_id},
            )
        ).fetchone()
        assert row is not None, "Trashed gallery must not be deleted"
        assert row[0] == "Original Title", "Title must not be overwritten by the re-download"
        assert row[1] == "complete", "download_status must not be flipped to 'downloading'"
        assert row[2] == 5, "pages must not change"
        assert row[3] is not None, "Gallery must remain in trash (deleted_at preserved)"

    async def test_import_file_is_noop_when_skipped_trashed(self, db_session, db_session_factory, tmp_path):
        """No image rows may be created while skipped_trashed is set."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source="trash_src", source_id="trash_imgs")
        await db_session.execute(
            text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :gid"),
            {"gid": gallery_id},
        )
        await db_session.commit()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "trash_src"
        importer.source_id = "trash_imgs"
        importer.skipped_trashed = True

        fake_file = tmp_path / "page.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        # store_blob must never be reached for a trashed gallery; mock it so the
        # test fails loudly if the guard is removed (rather than relying on a
        # downstream error swallowing the insert).
        store_blob_mock = AsyncMock()

        fake_factory = _make_session_factory_cm(db_session_factory)
        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive._sha256", return_value="ff" + "0" * 62),
            patch("worker.progressive.store_blob", store_blob_mock),
        ):
            await importer.import_file(fake_file)
            import asyncio

            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        store_blob_mock.assert_not_called()
        assert importer._processed == set(), "import_file must return before marking the file processed"

        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM images WHERE gallery_id = :gid"),
                {"gid": gallery_id},
            )
        ).scalar()
        assert count == 0, "import_file must be a no-op for a trashed gallery"

    async def test_cleanup_does_not_delete_trashed_gallery_when_skipped(self, db_session, db_session_factory):
        """cleanup() after a skipped trashed import must not delete the gallery (#53 guard)."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source="trash_src", source_id="trash_clean")
        await db_session.execute(
            text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :gid"),
            {"gid": gallery_id},
        )
        await db_session.commit()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "trash_src"
        importer.source_id = "trash_clean"
        importer.skipped_trashed = True

        fake_factory = _make_session_factory_cm(db_session_factory)
        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.library_dir", return_value=Path("/nonexistent/lib")),
            patch("worker.progressive.thumb_dir", return_value=Path("/nonexistent/thumb")),
        ):
            await importer.cleanup()

        row = (await db_session.execute(text("SELECT id FROM galleries WHERE id = :id"), {"id": gallery_id})).fetchone()
        assert row is not None, "cleanup() must not delete a pre-existing trashed gallery"


# ---------------------------------------------------------------------------
# TestProgressiveImporterAbort
# ---------------------------------------------------------------------------


class TestProgressiveImporterAbort:
    """Tests for ProgressiveImporter.abort()."""

    async def test_abort_preserves_gallery_as_partial(self, db_session, db_session_factory):
        """abort() must set download_status='partial' when images exist."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, pages=0)
        sha = "dddddd" + "0" * 58
        await _insert_blob(db_session, sha)
        await _insert_image(db_session, gallery_id, 1, sha)
        await _insert_image(db_session, gallery_id, 2, sha)

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"

        fake_factory = _make_session_factory_cm(db_session_factory)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer.abort()

        row = (
            await db_session.execute(
                text("SELECT download_status, pages FROM galleries WHERE id = :id"),
                {"id": gallery_id},
            )
        ).fetchone()

        assert row is not None
        assert row[0] == "partial", "Gallery download_status should be 'partial' after abort with images"
        assert row[1] == 2, "Gallery pages count should reflect actual image count"

    async def test_abort_no_images_sets_failed(self, db_session, db_session_factory):
        """abort() must set download_status='failed' (not 'downloading') when no images exist (edge case #16)."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, pages=0, download_status="downloading")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"

        fake_factory = _make_session_factory_cm(db_session_factory)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer.abort()

        row = (
            await db_session.execute(
                text("SELECT download_status, pages FROM galleries WHERE id = :id"),
                {"id": gallery_id},
            )
        ).fetchone()

        assert row is not None
        assert row[0] == "failed", "Zero-image abort must use terminal status 'failed', not stale 'downloading'"
        assert row[1] == 0, "Gallery pages should be 0 when no images"


# ---------------------------------------------------------------------------
# TestProgressiveImporterFinalize
# ---------------------------------------------------------------------------


class TestProgressiveImporterFinalize:
    """Tests for ProgressiveImporter.finalize()."""

    async def test_finalize_never_rmtrees_shared_gallery_root_wiping_concurrent_galleries(self, tmp_path):
        """finalize() must refuse to rmtree the shared gallery root, even when a
        caller passes it as dest_dir.

        Regression: a gallery-dl job whose dest_dir resolved to the /data/gallery
        root ran rmtree(root) in finalize(), deleting the staging dir of an EH
        gallery downloading concurrently under /data/gallery/ehentai/<gid>/
        (EH gid 3746208 incident — 262 pages lost, then ENOENT on metadata.json).
        """
        from worker.progressive import ProgressiveImporter

        root = tmp_path / "gallery"
        root.mkdir()
        # A concurrently-downloading EH gallery staging under the same root.
        victim = root / "ehentai" / "3746208"
        victim.mkdir(parents=True)
        (victim / "0001.webp").write_bytes(b"webp-data")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        # skipped_trashed takes the early rmtree branch — no DB needed.
        importer.skipped_trashed = True

        with patch("worker.progressive.settings") as mock_settings:
            mock_settings.data_gallery_path = str(root)
            await importer.finalize(root)

        assert root.exists(), "finalize must not delete the shared gallery root"
        assert (victim / "0001.webp").exists(), "concurrent gallery's staged file must survive"

    async def test_finalize_sets_complete_status(self, db_session, db_session_factory, tmp_path):
        """finalize(partial=False) must set download_status='complete' and correct pages count."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, pages=0)
        sha = "eeeeee" + "0" * 58
        await _insert_blob(db_session, sha)
        await _insert_image(db_session, gallery_id, 1, sha)
        await _insert_image(db_session, gallery_id, 2, sha)
        await _insert_image(db_session, gallery_id, 3, sha)

        dest_dir = tmp_path / "gallery_dl_dest"
        dest_dir.mkdir()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"
        importer._page_counter = 3

        fake_factory = _make_session_factory_cm(db_session_factory)

        mock_settings = MagicMock()
        mock_settings.tag_model_enabled = False

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("core.config.settings", mock_settings),
        ):
            result = await importer.finalize(dest_dir, partial=False)

        assert result == gallery_id

        row = (
            await db_session.execute(
                text("SELECT download_status, pages FROM galleries WHERE id = :id"),
                {"id": gallery_id},
            )
        ).fetchone()

        assert row is not None
        assert row[0] == "complete", "Gallery download_status should be 'complete' after finalize"
        assert row[1] == 3, "Gallery pages should match actual image count"

    async def test_finalize_partial_sets_partial_status(self, db_session, db_session_factory, tmp_path):
        """finalize(partial=True) must set download_status='partial'."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, pages=0)
        sha = "ffffff" + "0" * 58
        await _insert_blob(db_session, sha)
        await _insert_image(db_session, gallery_id, 1, sha)

        dest_dir = tmp_path / "gallery_dl_partial"
        dest_dir.mkdir()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"
        importer._page_counter = 1

        fake_factory = _make_session_factory_cm(db_session_factory)

        mock_settings = MagicMock()
        mock_settings.tag_model_enabled = False

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("core.config.settings", mock_settings),
        ):
            result = await importer.finalize(dest_dir, partial=True)

        assert result == gallery_id

        row = (
            await db_session.execute(
                text("SELECT download_status, pages FROM galleries WHERE id = :id"),
                {"id": gallery_id},
            )
        ).fetchone()

        assert row is not None
        assert row[0] == "partial", "Gallery download_status should be 'partial' after finalize(partial=True)"
        assert row[1] == 1, "Gallery pages should reflect actual image count"

    async def test_finalize_no_gallery_returns_none(self, tmp_path):
        """finalize() with no gallery_id must return None without raising."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        # gallery_id is None

        dest_dir = tmp_path / "no_gallery"
        dest_dir.mkdir()

        result = await importer.finalize(dest_dir, partial=False)
        assert result is None, "finalize() should return None when gallery_id is not set"


# ---------------------------------------------------------------------------
# TestProgressiveImporterEnsureGallery
# ---------------------------------------------------------------------------


def _make_mock_session_for_ensure(gallery_id: int):
    """Return a fully-mocked async session that pretends to execute pg_insert/RETURNING."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    # scalar_one() must return the fake gallery_id
    execute_result = MagicMock()
    execute_result.scalar_one = MagicMock(return_value=gallery_id)
    # scalar_one_or_none for max_page query in _load_gallery_state
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    # first() for the trashed-conflict pre-check (audit #8): no existing gallery
    execute_result.first = MagicMock(return_value=None)
    # scalars().all() for ExcludedBlob query in _load_gallery_state
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=[])
    execute_result.scalars = MagicMock(return_value=scalars_mock)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _cm():
        yield session

    class _Factory:
        def __call__(self):
            return _cm()

    return _Factory(), session


class TestProgressiveImporterEnsureGallery:
    """Tests for ProgressiveImporter.ensure_gallery_from_url."""

    async def test_ensure_gallery_from_url_creates_gallery_record(self):
        """ensure_gallery_from_url must return the gallery id from the DB."""
        from worker.progressive import ProgressiveImporter

        fake_factory, _ = _make_mock_session_for_ensure(gallery_id=42)
        importer = ProgressiveImporter(db_job_id=None, user_id=None)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            gid = await importer.ensure_gallery_from_url("https://example.com/comics/my_series", Path("/tmp/dest"))

        assert gid == 42
        assert importer.gallery_id == 42

    async def test_ensure_gallery_from_url_populates_source_and_source_id(self):
        """ensure_gallery_from_url must set source and source_id on the importer."""
        from worker.progressive import ProgressiveImporter

        fake_factory, _ = _make_mock_session_for_ensure(gallery_id=7)
        importer = ProgressiveImporter(db_job_id=None, user_id=None)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer.ensure_gallery_from_url("https://www.testsite.org/gallery/12345", Path("/tmp/dest"))

        # Path component "gallery" is used as source_id
        assert importer.source_id == "gallery"
        assert importer.source is not None

    async def test_ensure_gallery_from_url_duplicate_upserts_without_error(self):
        """Calling ensure_gallery_from_url twice with the same URL must not raise."""
        from worker.progressive import ProgressiveImporter

        fake_factory1, _ = _make_mock_session_for_ensure(gallery_id=10)
        importer1 = ProgressiveImporter(db_job_id=None, user_id=None)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory1):
            gid1 = await importer1.ensure_gallery_from_url("https://dup.example.com/art/9999", Path("/tmp/dest_dup"))

        fake_factory2, _ = _make_mock_session_for_ensure(gallery_id=10)
        importer2 = ProgressiveImporter(db_job_id=None, user_id=None)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory2):
            gid2 = await importer2.ensure_gallery_from_url("https://dup.example.com/art/9999", Path("/tmp/dest_dup"))

        assert isinstance(gid1, int)
        assert isinstance(gid2, int)


# ---------------------------------------------------------------------------
# TestProgressiveImporterImportFile
# ---------------------------------------------------------------------------


class TestProgressiveImporterImportFile:
    """Tests for ProgressiveImporter._import_single (via import_file)."""

    async def test_import_file_with_excluded_blob_is_skipped(self, db_session, db_session_factory, tmp_path):
        """A file whose sha256 is in the excluded set must be silently skipped."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session)
        sha = "ex" + "0" * 62

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "test_001"
        importer._excluded_set = {sha}

        # Create a minimal JPEG file
        fake_file = tmp_path / "excluded.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        fake_factory = _make_session_factory_cm(db_session_factory)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive._sha256", return_value=sha),
        ):
            await importer.import_file(fake_file)
            # Drain all tasks
            import asyncio

            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM images WHERE gallery_id=:gid"),
                {"gid": gallery_id},
            )
        ).scalar()
        assert count == 0, "Excluded blob must not produce an image record"

    async def test_import_file_validates_magic_bytes(self, db_session, db_session_factory, tmp_path):
        """File with invalid magic bytes must be skipped without importing."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source_id="magic_test")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "magic_test"

        # Write garbage bytes that fail magic check
        bad_file = tmp_path / "bad.jpg"
        bad_file.write_bytes(b"\x00\x01\x02\x03\x04")

        fake_factory = _make_session_factory_cm(db_session_factory)

        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer.import_file(bad_file)
            import asyncio

            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM images WHERE gallery_id=:gid"),
                {"gid": gallery_id},
            )
        ).scalar()
        assert count == 0, "File with invalid magic bytes must not be imported"

    async def test_same_source_item_new_hash_creates_replacement(
        self, db_session, db_session_factory, tmp_path, monkeypatch
    ):
        """A changed source item should preserve the old row as replaced and insert the new blob at the same page."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from db.models import Blob
        from worker import progressive as progressive_mod
        from worker.progressive import ProgressiveImporter

        monkeypatch.setattr(progressive_mod, "pg_insert", sqlite_insert)
        monkeypatch.setattr(progressive_mod.Image.__table__.c.tags_array, "default", None)

        gallery_id = await _insert_gallery(db_session, source="pixiv", source_id="123", pages=1)
        old_sha = "aa" + "0" * 62
        new_sha = "bb" + "0" * 62
        await _insert_blob(db_session, old_sha, ref_count=1)
        await _insert_blob(db_session, new_sha, ref_count=0)
        old_id = await _insert_image(
            db_session,
            gallery_id,
            1,
            old_sha,
            filename="0001.jpg",
            source_item_id="pixiv:123:p1",
        )

        importer = ProgressiveImporter(db_job_id=None, user_id=None, page_num_from_filename=True)
        importer.gallery_id = gallery_id
        importer.source = "pixiv"
        importer.source_id = "123"

        fake_file = tmp_path / "0001.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        fake_factory = _make_session_factory_cm(db_session_factory)
        replacement_blob = Blob(sha256=new_sha, file_size=100, extension=".jpg", storage="cas", ref_count=0)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.store_blob", new=AsyncMock(return_value=replacement_blob)),
            patch("worker.progressive.create_library_symlink", new=AsyncMock()),
        ):
            await importer._load_gallery_state()
            await importer.import_file(fake_file, sha256=new_sha)
            import asyncio

            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        rows = (
            await db_session.execute(
                text(
                    "SELECT id, page_num, blob_sha256, visibility, replaced_by_image_id "
                    "FROM images WHERE gallery_id=:gid ORDER BY page_num"
                ),
                {"gid": gallery_id},
            )
        ).all()
        assert len(rows) == 2
        old_row = next(row for row in rows if row.id == old_id)
        new_row = next(row for row in rows if row.blob_sha256 == new_sha)
        assert old_row.visibility == "replaced"
        assert old_row.page_num < 0
        assert old_row.replaced_by_image_id == new_row.id
        assert new_row.page_num == 1
        assert new_row.visibility == "active"

    async def test_replacement_preserves_hidden_state(self, db_session, db_session_factory, tmp_path, monkeypatch):
        """A hidden source item that changes hash should stay hidden after replacement."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from db.models import Blob
        from worker import progressive as progressive_mod
        from worker.progressive import ProgressiveImporter

        monkeypatch.setattr(progressive_mod, "pg_insert", sqlite_insert)
        monkeypatch.setattr(progressive_mod.Image.__table__.c.tags_array, "default", None)

        gallery_id = await _insert_gallery(db_session, source="pixiv", source_id="456", pages=0)
        old_sha = "cc" + "0" * 62
        new_sha = "dd" + "0" * 62
        await _insert_blob(db_session, old_sha, ref_count=1)
        await _insert_blob(db_session, new_sha, ref_count=0)
        await _insert_image(
            db_session,
            gallery_id,
            1,
            old_sha,
            filename="0001.jpg",
            visibility="user_hidden",
            source_item_id="pixiv:456:p1",
        )

        importer = ProgressiveImporter(db_job_id=None, user_id=None, page_num_from_filename=True)
        importer.gallery_id = gallery_id
        importer.source = "pixiv"
        importer.source_id = "456"

        fake_file = tmp_path / "0001.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        fake_factory = _make_session_factory_cm(db_session_factory)
        replacement_blob = Blob(sha256=new_sha, file_size=100, extension=".jpg", storage="cas", ref_count=0)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.store_blob", new=AsyncMock(return_value=replacement_blob)),
            patch("worker.progressive.create_library_symlink", new=AsyncMock()),
        ):
            await importer._load_gallery_state()
            await importer.import_file(fake_file, sha256=new_sha)
            import asyncio

            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        new_visibility = (
            await db_session.execute(
                text("SELECT visibility FROM images WHERE gallery_id=:gid AND blob_sha256=:sha"),
                {"gid": gallery_id, "sha": new_sha},
            )
        ).scalar_one()
        assert new_visibility == "user_hidden"

    async def test_import_file_does_not_reserve_page_before_validation(self, tmp_path):
        """Sequential imports should not reserve page numbers until the file is validated and stored."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = 1
        importer.source = "test"
        importer.source_id = "test_001"

        # Create fake valid files; _import_single is mocked, so no validated insert occurs.
        f1 = tmp_path / "img1.jpg"
        f2 = tmp_path / "img2.jpg"
        f3 = tmp_path / "img3.jpg"
        for f in (f1, f2, f3):
            f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        with patch.object(importer, "_import_single", new=AsyncMock()):
            await importer.import_file(f1)
            await importer.import_file(f2)
            await importer.import_file(f3)

        assert importer._page_counter == 0

    async def test_import_file_deduplicates_same_path(self, tmp_path):
        """Passing the same file path twice must only increment counter once."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = 1
        importer.source = "test"
        importer.source_id = "test_001"

        f = tmp_path / "dup.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        with patch.object(importer, "_import_single", new=AsyncMock()):
            await importer.import_file(f)
            await importer.import_file(f)  # duplicate — must be ignored

        assert importer._page_counter == 0


# ---------------------------------------------------------------------------
# TestProgressiveImporterPageNumbering
# ---------------------------------------------------------------------------


class TestProgressiveImporterPageNumbering:
    """Tests for the page numbering behaviour of ProgressiveImporter."""

    async def test_page_numbering_starts_from_zero_offset(self, tmp_path):
        """First file imported must receive page_num=1 (counter starts at 0)."""
        import asyncio

        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = 1
        importer.source = "test"
        importer.source_id = "test_001"

        captured_pages: list[int] = []

        async def _capture(file_path, page_num, sha256=None):
            captured_pages.append(page_num)

        f = tmp_path / "p1.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        with patch.object(importer, "_import_single", new=_capture):
            await importer.import_file(f)
            # Drain spawned asyncio tasks so _capture is actually called
            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        assert captured_pages == [None]

    async def test_sequential_page_numbering_maintained(self, tmp_path):
        """Files imported sequentially must receive consecutive page numbers."""
        import asyncio

        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = 1
        importer.source = "test"
        importer.source_id = "test_001"

        captured_pages: list[int] = []

        async def _capture(file_path, page_num, sha256=None):
            captured_pages.append(page_num)

        files = []
        for i in range(1, 6):
            f = tmp_path / f"page{i}.jpg"
            f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
            files.append(f)

        with patch.object(importer, "_import_single", new=_capture):
            for f in files:
                await importer.import_file(f)
            # Drain all spawned tasks
            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        assert captured_pages == [None, None, None, None, None]

    async def test_page_counter_resumes_from_loaded_max(self, db_session, db_session_factory, tmp_path):
        """After _load_gallery_state, new pages must continue from existing max page_num."""
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source_id="resume_test")
        sha = "rr" + "0" * 62
        await _insert_blob(db_session, sha)
        # Pre-existing image at page_num=5
        await _insert_image(db_session, gallery_id, 5, sha)

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "resume_test"

        fake_factory = _make_session_factory_cm(db_session_factory)
        with patch("worker.progressive.AsyncSessionLocal", fake_factory):
            await importer._load_gallery_state()

        assert importer._page_counter == 5, "Counter must resume from existing max page_num so new pages start at 6"

    def test_pixiv_prefixed_filename_source_item_id_is_normalized(self):
        """Pixiv user-work filenames should map to the same illust/page identity format as artwork pages."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None, page_num_from_filename=True)
        importer.source = "pixiv"
        importer.source_id = "user_999"

        source_item_id = importer._derive_source_item_id(Path("123456_p0002.jpg"), 2, "a" * 64)

        assert source_item_id == "pixiv:123456:p2"

    async def test_pixiv_prefixed_filenames_use_unique_sequence_page_numbers(self, tmp_path):
        """Pixiv user-work page filenames must not collide on repeated _p0001 suffixes."""
        import asyncio

        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None, page_num_from_filename=True)
        importer.gallery_id = 1
        importer.source = "pixiv"
        importer.source_id = "user_999"

        captured_pages: list[int] = []

        async def _capture(file_path, page_num, sha256=None):
            captured_pages.append(page_num)

        files = [tmp_path / "123456_p0001.jpg", tmp_path / "654321_p0001.jpg"]
        for f in files:
            f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        with patch.object(importer, "_import_single", new=_capture):
            for f in files:
                await importer.import_file(f)
            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        assert captured_pages == [1, 2]


# ---------------------------------------------------------------------------
# TestProgressiveImporterSymlinkGuard — edge case #48
# ---------------------------------------------------------------------------


class TestProgressiveImporterSymlinkGuard:
    """Regression tests for edge case #48: library symlinks must only be created
    when an Image row was actually inserted.

    _import_single used to call create_library_symlink() unconditionally after
    the on-conflict insert, so a conflicting insert (no row created) still wrote
    a symlink — leaving filesystem state the DB does not represent, which
    reconciliation then treats as authoritative.
    """

    def _conflict_factory(self, db_session_factory):
        """Session factory whose sessions report a conflict (no row) for any
        INSERT into images, delegating everything else to the real session."""

        class _ImagesInsertConflictSession:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            async def execute(self, stmt, *args, **kwargs):
                table = getattr(stmt, "table", None)
                if getattr(stmt, "is_insert", False) and getattr(table, "name", None) == "images":
                    res = MagicMock()
                    res.scalar_one_or_none.return_value = None
                    return res
                return await self._real.execute(stmt, *args, **kwargs)

        @asynccontextmanager
        async def _cm():
            async with db_session_factory() as session:
                yield _ImagesInsertConflictSession(session)

        class _Factory:
            def __call__(self):
                return _cm()

        return _Factory()

    async def test_insert_conflict_without_image_row_does_not_create_symlink(
        self, db_session, db_session_factory, tmp_path
    ):
        """When the images insert conflicts (returns no row), no library symlink
        may be created for the file."""
        import asyncio

        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source_id="symlink_guard")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "symlink_guard"

        fake_file = tmp_path / "001.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        mock_blob = MagicMock()
        mock_blob.sha256 = "aa" * 32
        symlink_spy = AsyncMock()

        with (
            patch("worker.progressive.AsyncSessionLocal", self._conflict_factory(db_session_factory)),
            patch("worker.progressive.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.progressive._sha256", return_value="aa" * 32),
            patch("worker.progressive.create_library_symlink", symlink_spy),
        ):
            await importer.import_file(fake_file)
            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        symlink_spy.assert_not_called()

    async def test_inserted_image_row_still_creates_symlink(
        self, db_session, db_session_factory, tmp_path, monkeypatch
    ):
        """Control: a successful insert must keep creating the library symlink."""
        import asyncio

        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from worker import progressive as progressive_mod
        from worker.progressive import ProgressiveImporter

        monkeypatch.setattr(progressive_mod, "pg_insert", sqlite_insert)
        monkeypatch.setattr(progressive_mod.Image.__table__.c.tags_array, "default", None)

        gallery_id = await _insert_gallery(db_session, source_id="symlink_ok")

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "symlink_ok"

        fake_file = tmp_path / "001.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        mock_blob = MagicMock()
        mock_blob.sha256 = "bb" * 32
        symlink_spy = AsyncMock()
        fake_factory = _make_session_factory_cm(db_session_factory)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.progressive._sha256", return_value="bb" * 32),
            patch("worker.progressive.create_library_symlink", symlink_spy),
        ):
            await importer.import_file(fake_file)
            if importer._tasks:
                await asyncio.gather(*importer._tasks, return_exceptions=True)

        symlink_spy.assert_called_once()
        assert symlink_spy.call_args.args[2] == "001.jpg"


# ---------------------------------------------------------------------------
# Disaster-recovery sidecar wiring (info.json)
# ---------------------------------------------------------------------------


class TestProgressiveFinalizeSidecar:
    """finalize() must write the info.json disaster-recovery sidecar."""

    async def test_finalize_writes_info_json_sidecar(self, db_session, db_session_factory, tmp_path):
        from worker.progressive import ProgressiveImporter

        gallery_id = await _insert_gallery(db_session, source_id="sidecar_fin", pages=0)
        sha = "dddddd" + "0" * 58
        await _insert_blob(db_session, sha)
        await _insert_image(db_session, gallery_id, 1, sha)

        dest_dir = tmp_path / "gallery_dl_dest"
        dest_dir.mkdir()

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = gallery_id
        importer.source = "test_source"
        importer.source_id = "sidecar_fin"

        fake_factory = _make_session_factory_cm(db_session_factory)
        mock_settings = MagicMock()
        mock_settings.tag_model_enabled = False
        sidecar_spy = AsyncMock(return_value=True)

        with (
            patch("worker.progressive.AsyncSessionLocal", fake_factory),
            patch("worker.progressive.write_gallery_sidecar", sidecar_spy),
            patch("core.config.settings", mock_settings),
        ):
            result = await importer.finalize(dest_dir, partial=False)

        assert result == gallery_id
        sidecar_spy.assert_awaited_once()
        source, source_id, payload = sidecar_spy.call_args.args
        assert source == "test_source"
        assert source_id == "sidecar_fin"
        assert payload["title"] == "Test Gallery"
