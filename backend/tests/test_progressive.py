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
) -> int:
    """Insert an image row and return its id."""
    result = await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256) "
            "VALUES (:gid, :page_num, :filename, :sha) "
            "RETURNING id"
        ),
        {"gid": gallery_id, "page_num": page_num, "filename": filename, "sha": blob_sha256},
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

    async def test_abort_no_images_sets_downloading(self, db_session, db_session_factory):
        """abort() must keep download_status='downloading' when no images exist."""
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
        assert row[0] == "downloading", "Gallery download_status should remain 'downloading' when no images"
        assert row[1] == 0, "Gallery pages should be 0 when no images"

# ---------------------------------------------------------------------------
# TestProgressiveImporterFinalize
# ---------------------------------------------------------------------------

class TestProgressiveImporterFinalize:
    """Tests for ProgressiveImporter.finalize()."""

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

    async def test_import_file_increments_page_counter(self, tmp_path):
        """Each call to import_file must increment _page_counter by 1."""
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.gallery_id = 1
        importer.source = "test"
        importer.source_id = "test_001"

        # Create fake valid files (import_file assigns page_num before spawning task)
        f1 = tmp_path / "img1.jpg"
        f2 = tmp_path / "img2.jpg"
        f3 = tmp_path / "img3.jpg"
        for f in (f1, f2, f3):
            f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        # We only test that the serial counter advances — mock _import_single
        with patch.object(importer, "_import_single", new=AsyncMock()):
            await importer.import_file(f1)
            await importer.import_file(f2)
            await importer.import_file(f3)

        assert importer._page_counter == 3

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

        assert importer._page_counter == 1

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

        assert captured_pages == [1]

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

        assert captured_pages == [1, 2, 3, 4, 5]

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
