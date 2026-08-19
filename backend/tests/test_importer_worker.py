"""Tests for worker/importer.py — import pipeline.

Covers:
- _extract_tags: dict metadata, list metadata, tags.txt fallback, no tags
- _build_gallery: title fallback chain, posted_at parsing (int, ISO string, invalid),
  full metadata population
- import_job: non-directory path, empty directory, successful import flow
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on sys.path (conftest does this too, but guard here for safety)
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx():
    """Build a minimal SAQ ctx dict with a mock Redis."""
    redis = AsyncMock()
    return {"redis": redis}


def _make_mock_session():
    """Build an AsyncMock that mimics an SQLAlchemy async session.

    Supports:
    - execute() → result with scalar_one() = 1 and scalars().all() = []
    - flush(), commit() as AsyncMock
    """
    session = AsyncMock()

    result = MagicMock()
    result.scalar_one = MagicMock(return_value=1)
    result.scalar_one_or_none = MagicMock(return_value=1)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=MagicMock())
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@asynccontextmanager
async def _mock_session_ctx(session):
    """Async context manager that yields a pre-built mock session."""
    yield session


def _create_test_gallery(tmp_path: Path, metadata: dict | None = None) -> Path:
    """Create a minimal gallery directory with a fake JPEG and optional metadata."""
    gallery_dir = tmp_path / "test_gallery"
    gallery_dir.mkdir()
    # JPEG magic bytes
    (gallery_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    if metadata is not None:
        (gallery_dir / "metadata.json").write_text(json.dumps(metadata))
    return gallery_dir


async def test_batch_import_records_manual_conflict_without_reimport():
    from db.models import Gallery, ImportConflict
    from worker.importer import batch_import_job

    redis = AsyncMock()
    redis.get.return_value = b"manual"
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = Gallery(
        id=77,
        source="local",
        source_id="duplicate",
        title="Existing",
    )
    session.execute.return_value = result
    with patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(session)):
        output = await batch_import_job(
            {"redis": redis},
            root_dir="/mnt/library",
            mode="link",
            galleries=[{"path": "/mnt/library/duplicate", "title": "Incoming"}],
            batch_id="batch-manual",
            user_id=1,
        )

    conflict = session.add.call_args.args[0]
    assert isinstance(conflict, ImportConflict)
    assert conflict.existing_gallery_id == 77
    assert conflict.incoming_payload["path"] == "/mnt/library/duplicate"
    assert output["conflicts"] == 1


# ---------------------------------------------------------------------------
# _extract_tags tests
# ---------------------------------------------------------------------------


class TestExtractTags:
    """Unit tests for worker.importer._extract_tags (pure function)."""

    def test_dict_tags_expanded_to_namespace_colon_name(self, tmp_path):
        """Dict-form tags must be expanded to 'namespace:name' strings."""
        from worker.importer import _extract_tags

        metadata = {"tags": {"artist": ["foo"], "female": ["bar", "baz"]}}
        result = _extract_tags(tmp_path, metadata)
        assert "artist:foo" in result
        assert "female:bar" in result
        assert "female:baz" in result
        assert len(result) == 3

    def test_list_tags_returned_as_is(self, tmp_path):
        """List-form tags must be passed through unchanged."""
        from worker.importer import _extract_tags

        metadata = {"tags": ["artist:foo", "language:english"]}
        result = _extract_tags(tmp_path, metadata)
        assert result == ["artist:foo", "language:english"]

    def test_tags_txt_fallback_when_no_metadata_tags(self, tmp_path):
        """When metadata has no tags, fall back to reading tags.txt."""
        from worker.importer import _extract_tags

        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("artist:foo\nfemale:bar\n\n")
        result = _extract_tags(tmp_path, {})
        assert result == ["artist:foo", "female:bar"]

    def test_empty_tags_when_no_metadata_and_no_tags_txt(self, tmp_path):
        """No metadata tags and no tags.txt must return an empty list."""
        from worker.importer import _extract_tags

        result = _extract_tags(tmp_path, {})
        assert result == []

    def test_tags_txt_blank_lines_stripped(self, tmp_path):
        """Blank lines in tags.txt must not produce empty tag strings."""
        from worker.importer import _extract_tags

        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("\n\nartist:foo\n   \ngeneral:test\n")
        result = _extract_tags(tmp_path, {})
        assert result == ["artist:foo", "general:test"]

    def test_dict_tags_with_empty_namespace_list(self, tmp_path):
        """A namespace with an empty list in dict-form tags must produce no entries."""
        from worker.importer import _extract_tags

        metadata = {"tags": {"artist": [], "female": ["bar"]}}
        result = _extract_tags(tmp_path, metadata)
        assert result == ["female:bar"]


# ---------------------------------------------------------------------------
# _build_gallery tests
# ---------------------------------------------------------------------------


class TestBuildGallery:
    """Unit tests for worker.importer._build_gallery (pure function)."""

    def _call(self, source="ehentai", source_id="12345", meta=None, tags=None, pages=10):
        from worker.importer import _build_gallery

        if meta is None:
            meta = {}
        if tags is None:
            tags = []
        with patch(
            "plugins.builtin.gallery_dl._metadata._extract_artist",
            return_value=None,
        ):
            return _build_gallery(source, source_id, meta, tags, pages)

    def test_title_uses_title_field_first(self):
        """'title' field must be used when present."""
        meta = {"title": "Main Title", "title_en": "English Title"}
        result = self._call(meta=meta)
        assert result["title"] == "Main Title"

    def test_title_falls_back_to_title_en(self):
        """When 'title' is absent, 'title_en' must be used."""
        meta = {"title_en": "English Title"}
        result = self._call(meta=meta)
        assert result["title"] == "English Title"

    def test_title_falls_back_to_description_truncated(self):
        """When both title fields are absent, description[:120] must be used."""
        meta = {"description": "A" * 200}
        result = self._call(meta=meta)
        assert result["title"] == "A" * 120

    def test_title_falls_back_to_source_id_when_all_empty(self):
        """When all text fields are absent, title must be 'source_source_id'."""
        result = self._call(source="ehentai", source_id="99999", meta={})
        assert result["title"] == "ehentai_99999"

    def test_posted_at_from_integer_timestamp(self):
        """Integer 'date' field must be parsed as a UTC datetime."""
        ts = 1_700_000_000
        meta = {"date": ts}
        result = self._call(meta=meta)
        expected = datetime.fromtimestamp(ts, tz=UTC)
        assert result["posted_at"] == expected

    def test_posted_at_from_iso_string(self):
        """ISO-format 'date' string must be parsed to a datetime."""
        iso = "2024-01-15T12:00:00"
        meta = {"date": iso}
        result = self._call(meta=meta)
        assert result["posted_at"] == datetime.fromisoformat(iso)

    def test_posted_at_invalid_value_returns_none_without_crash(self):
        """An unparseable 'date' value must result in None — not a crash."""
        meta = {"date": "not-a-date"}
        result = self._call(meta=meta)
        assert result["posted_at"] is None

    def test_full_metadata_populates_all_fields(self):
        """All metadata fields must be transferred to the gallery dict."""
        meta = {
            "title": "Full Gallery",
            "title_jpn": "フルギャラリー",
            "category": "ehentai",
            "lang": "japanese",
            "uploader": "uploader_name",
            "date": 1_700_000_000,
        }
        tags = ["artist:test", "female:glasses"]
        result = self._call(meta=meta, tags=tags, pages=42)

        assert result["source"] == "ehentai"
        assert result["title"] == "Full Gallery"
        assert result["title_jpn"] == "フルギャラリー"
        assert result["category"] == "ehentai"
        assert result["language"] == "japanese"
        assert result["uploader"] == "uploader_name"
        assert result["pages"] == 42
        assert result["tags_array"] == tags
        assert result["download_status"] == "complete"
        assert result["posted_at"] is not None

    def test_posted_at_float_timestamp_parsed(self):
        """Float 'date' field (unix timestamp) must be parsed without error."""
        ts = 1_700_000_000.5
        meta = {"date": ts}
        result = self._call(meta=meta)
        assert result["posted_at"] is not None
        assert isinstance(result["posted_at"], datetime)

    def test_posted_field_used_as_fallback_for_date(self):
        """When 'date' is absent, 'posted' field must be used for posted_at."""
        ts = 1_600_000_000
        meta = {"posted": ts}
        result = self._call(meta=meta)
        assert result["posted_at"] == datetime.fromtimestamp(ts, tz=UTC)


# ---------------------------------------------------------------------------
# import_job tests
# ---------------------------------------------------------------------------


class TestImportJob:
    """Integration-level tests for worker.importer.import_job."""

    async def test_non_directory_path_returns_failed(self, tmp_path):
        """A path that is not a directory must return status=failed immediately."""
        from worker.importer import import_job

        fake_path = str(tmp_path / "does_not_exist")
        result = await import_job(_make_ctx(), path=fake_path)

        assert result["status"] == "failed"
        assert "not a directory" in result["error"]

    async def test_empty_directory_returns_failed(self, tmp_path):
        """A directory with no recognised media files must return status=failed."""
        from worker.importer import import_job

        empty_dir = tmp_path / "empty_gallery"
        empty_dir.mkdir()

        with (
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=MagicMock(
                    source_id="gallery_dl",
                    source_id_fields=(),
                    category="gallery",
                ),
            ),
        ):
            result = await import_job(_make_ctx(), path=str(empty_dir))

        assert result["status"] == "failed"
        assert "no media files found" in result["error"]

    async def test_file_path_instead_of_directory_returns_failed(self, tmp_path):
        """Passing a file path (not a directory) must return status=failed."""
        from worker.importer import import_job

        file_path = tmp_path / "notadir.jpg"
        file_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)

        result = await import_job(_make_ctx(), path=str(file_path))

        assert result["status"] == "failed"
        assert "not a directory" in result["error"]

    async def test_successful_import_returns_done(self, tmp_path):
        """A directory with valid images and mocked DB must return status=done."""
        from worker.importer import import_job

        gallery_dir = _create_test_gallery(
            tmp_path,
            metadata={
                "category": "ehentai",
                "title": "Test Gallery",
                "tags": {"artist": ["test_artist"]},
                "gid": 12345,
            },
        )

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        mock_blob.sha256 = "abc123"

        _site_cfg = MagicMock(
            source_id="ehentai",
            source_id_fields=("gid",),
            category="gallery",
        )

        with (
            patch(
                "worker.importer.AsyncSessionLocal",
                return_value=_mock_session_ctx(mock_session),
            ),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.helpers._sha256", return_value="abc" * 21 + "ab"),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=_site_cfg,
            ),
            patch(
                "plugins.registry.plugin_registry.get_parser",
                return_value=None,
            ),
            patch(
                "plugins.builtin.gallery_dl._metadata._extract_artist",
                return_value="ehentai:test_artist",
            ),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            ctx = _make_ctx()
            result = await import_job(ctx, path=str(gallery_dir), user_id=1)

        assert result["status"] == "done"
        assert "gallery_id" in result

    async def test_successful_import_enqueues_thumbnail_job(self, tmp_path):
        """After a successful import, thumbnail_job must be enqueued."""
        from worker.importer import import_job

        gallery_dir = _create_test_gallery(
            tmp_path,
            metadata={"category": "ehentai", "title": "T", "gid": 999},
        )

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        mock_blob.sha256 = "deadbeef" * 8

        _site_cfg = MagicMock(
            source_id="ehentai",
            source_id_fields=("gid",),
            category="gallery",
        )

        with (
            patch(
                "worker.importer.AsyncSessionLocal",
                return_value=_mock_session_ctx(mock_session),
            ),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.helpers._sha256", return_value="aa" * 32),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=_site_cfg,
            ),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch(
                "plugins.builtin.gallery_dl._metadata._extract_artist",
                return_value=None,
            ),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            ctx = _make_ctx()
            await import_job(ctx, path=str(gallery_dir))

        mock_enqueue.assert_any_call(
            "cover_thumbnail_job",
            gallery_id=1,
            _timeout=300,
            _job_id="cover-thumbnail:1",
        )
        mock_enqueue.assert_any_call(
            "thumbnail_job",
            gallery_id=1,
            _timeout=3600,
            _job_id="thumbnail:1",
        )
        assert [c.args[0] for c in mock_enqueue.call_args_list[:2]] == [
            "cover_thumbnail_job",
            "thumbnail_job",
        ]

    async def test_files_with_invalid_magic_bytes_are_skipped(self, tmp_path):
        """Files failing magic-byte validation must be skipped (counted but not imported)."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "gallery"
        gallery_dir.mkdir()
        # Two files: first has invalid magic, second is valid JPEG
        (gallery_dir / "bad.jpg").write_bytes(b"NOTJPEG" + b"\x00" * 100)
        (gallery_dir / "good.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        mock_blob.sha256 = "cc" * 32

        _site_cfg = MagicMock(
            source_id="gallery_dl",
            source_id_fields=(),
            category="gallery",
        )

        store_calls = []

        async def _fake_store(f, sha, session):
            store_calls.append(f.name)
            return mock_blob

        with (
            patch(
                "worker.importer.AsyncSessionLocal",
                return_value=_mock_session_ctx(mock_session),
            ),
            patch("worker.importer.store_blob", side_effect=_fake_store),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.helpers._sha256", return_value="dd" * 32),
            # Real magic-byte check — bad.jpg has bad bytes, good.jpg has JPEG magic
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=_site_cfg,
            ),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch(
                "plugins.builtin.gallery_dl._metadata._extract_artist",
                return_value=None,
            ),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            ctx = _make_ctx()
            result = await import_job(ctx, path=str(gallery_dir))

        # bad.jpg must not be stored; good.jpg must be stored
        assert result["status"] == "done"
        assert "bad.jpg" not in store_calls
        assert "good.jpg" in store_calls

    async def test_directory_without_json_metadata_uses_path_heuristic(self, tmp_path):
        """Galleries without metadata.json must infer source from directory path parts."""
        from worker.importer import import_job

        # Create an ehentai-named parent dir so the heuristic fires
        parent = tmp_path / "ehentai"
        parent.mkdir()
        gallery_dir = parent / "12345"
        gallery_dir.mkdir()
        (gallery_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        # No metadata.json

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        mock_blob.sha256 = "ee" * 32

        _site_cfg = MagicMock(
            source_id="ehentai",
            source_id_fields=(),
            category="gallery",
        )

        with (
            patch(
                "worker.importer.AsyncSessionLocal",
                return_value=_mock_session_ctx(mock_session),
            ),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.helpers._sha256", return_value="ff" * 32),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=_site_cfg,
            ),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch(
                "plugins.builtin.gallery_dl._metadata._extract_artist",
                return_value=None,
            ),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            ctx = _make_ctx()
            result = await import_job(ctx, path=str(gallery_dir))

        assert result["status"] == "done"

    async def test_trashed_conflict_is_not_mutated_and_staging_is_preserved(self, tmp_path):
        """HR-017: the guarded upsert returning no row must skip all ingest work."""
        from worker.importer import import_job

        gallery_dir = _create_test_gallery(tmp_path)
        session = _make_mock_session()
        session.execute.return_value.scalar_one_or_none.return_value = None
        store_spy = AsyncMock()
        site_cfg = MagicMock(source_id="gallery_dl", source_id_fields=(), category="gallery")

        with (
            patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(session)),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda tags, source: tags),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("plugins.builtin.gallery_dl._metadata._extract_artist", return_value=None),
            patch("worker.importer.store_blob", store_spy),
        ):
            result = await import_job(_make_ctx(), path=str(gallery_dir))

        assert result["status"] == "skipped_trashed"
        assert gallery_dir.exists()
        store_spy.assert_not_awaited()
        session.rollback.assert_awaited_once()

    async def test_hash_failure_sets_partial_and_preserves_staging(self, tmp_path):
        """HR-016: a dropped file must be visible in status and remain recoverable."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "hash_partial"
        gallery_dir.mkdir()
        good = gallery_dir / "001.jpg"
        bad = gallery_dir / "002.jpg"
        good.write_bytes(b"\xff\xd8\xff\xe0good")
        bad.write_bytes(b"\xff\xd8\xff\xe0bad")
        session = _make_mock_session()
        site_cfg = MagicMock(source_id="gallery_dl", source_id_fields=(), category="gallery")

        def _hash(path):
            if path.name == "002.jpg":
                raise OSError("unreadable")
            return "aa" * 32

        with (
            patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(session)),
            patch("worker.importer._sha256", side_effect=_hash),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda tags, source: tags),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("plugins.builtin.gallery_dl._metadata._extract_artist", return_value=None),
            patch("worker.importer.store_blob", AsyncMock(return_value=MagicMock())),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
        ):
            result = await import_job(_make_ctx(), path=str(gallery_dir))

        assert result["status"] == "partial"
        assert result["import_failures"][0]["filename"] == "002.jpg"
        assert gallery_dir.exists()


# ---------------------------------------------------------------------------
# TestLocalImportJob  (STAB-005 regression)
# ---------------------------------------------------------------------------


def _hash_stub(test_sha: str):
    """local_import_job now pins the digest to the bytes it hashed.

    Returning the real stat keeps the commit-boundary re-check satisfied while
    the digest itself stays fixed for the assertions.
    """
    from worker.source_identity import SourceFileIdentity

    def _hash(path):
        return test_sha, SourceFileIdentity._from_stat(path, path.stat())

    return _hash


def _make_local_import_sessions(test_sha: str):
    """Returns (s1, s2, s3) where:
    s1 — gallery lookup session
    s2 — excluded-blobs session (empty result)
    s3 — main session: image-rows query + count query + gallery get
    """
    mock_gallery = MagicMock()
    mock_gallery.source = "local"
    mock_gallery.source_id = "g1"
    mock_gallery.source_path = None
    mock_gallery.deleted_at = None

    s1 = AsyncMock()
    s1.get = AsyncMock(return_value=mock_gallery)

    s2 = AsyncMock()
    excl_result = MagicMock()
    excl_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    s2.execute = AsyncMock(return_value=excl_result)

    s3 = AsyncMock()
    s3.get = AsyncMock(return_value=mock_gallery)

    img_row = MagicMock()
    img_row.blob_sha256 = test_sha
    img_row.page_num = 1
    img_result = MagicMock()
    img_result.all = MagicMock(return_value=[img_row])

    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=1)

    s3.execute = AsyncMock(side_effect=[img_result, count_result])
    return s1, s2, s3


def _session_rotator(sessions):
    """Return an async context manager factory that yields sessions in order."""
    it = iter(sessions)

    @asynccontextmanager
    async def _next():
        yield next(it)

    return _next


class TestLocalImportJob:
    """Regression tests for local_import_job no-op guard (STAB-005).

    Verifies that thumbnail jobs are only enqueued when there is actual work
    to do, preventing duplicate render backlog on replayed local-import jobs.
    """

    async def test_no_thumbnail_enqueue_when_all_files_already_imported_and_thumbs_complete(self, tmp_path):
        """When all files are already imported and all thumbs are complete, no enqueue occurs."""
        from worker.importer import local_import_job

        gallery_dir = _create_test_gallery(tmp_path)
        test_sha = "aa" * 32

        td = tmp_path / "thumbs"
        td.mkdir()
        for size in (160, 360, 720):
            (td / f"thumb_{size}.webp").write_bytes(b"x")
        (td / ".thumbnail-version").write_text("2", encoding="ascii")

        s1, s2, s3 = _make_local_import_sessions(test_sha)

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_session_rotator([s1, s2, s3])),
            patch("worker.importer.hash_file_with_identity", side_effect=_hash_stub(test_sha)),
            patch("worker.importer.thumb_dir", return_value=td),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            result = await local_import_job(_make_ctx(), source_dir=str(gallery_dir), mode="copy", gallery_id=1)

        assert result["status"] == "done"
        mock_enqueue.assert_not_called()

    async def test_thumbnail_enqueued_when_existing_blobs_have_missing_thumbs(self, tmp_path):
        """When files are already imported but thumbs are incomplete, enqueue still fires."""
        from worker.importer import local_import_job

        gallery_dir = _create_test_gallery(tmp_path)
        test_sha = "bb" * 32

        # No thumb files created → existing_missing_thumb becomes True
        td = tmp_path / "thumbs"
        td.mkdir()

        s1, s2, s3 = _make_local_import_sessions(test_sha)

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_session_rotator([s1, s2, s3])),
            patch("worker.importer.hash_file_with_identity", side_effect=_hash_stub(test_sha)),
            patch("worker.importer.thumb_dir", return_value=td),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            result = await local_import_job(_make_ctx(), source_dir=str(gallery_dir), mode="copy", gallery_id=1)

        assert result["status"] == "done"
        mock_enqueue.assert_any_call(
            "cover_thumbnail_job",
            gallery_id=1,
            _timeout=300,
            _job_id="cover-thumbnail:1",
        )
        mock_enqueue.assert_any_call(
            "thumbnail_job",
            gallery_id=1,
            _timeout=3600,
            _job_id="thumbnail:1",
        )

    async def test_trashed_gallery_is_a_noop(self, tmp_path):
        """HR-014: a stale local import job must not touch a trashed gallery."""
        from worker.importer import local_import_job

        gallery_dir = _create_test_gallery(tmp_path)
        session = AsyncMock()
        gallery = MagicMock(source="local", source_id="trashed")
        gallery.deleted_at = datetime.now(UTC)
        session.get.return_value = gallery
        with (
            patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(session)),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256") as hash_spy,
        ):
            result = await local_import_job(_make_ctx(), str(gallery_dir), "copy", 9)

        assert result == {"status": "skipped_trashed", "gallery_id": 9}
        hash_spy.assert_not_called()


# ---------------------------------------------------------------------------
# local_import_job — symlink guard (edge case #48)
# ---------------------------------------------------------------------------


class TestLocalImportSymlinkGuard:
    """Regression tests for edge case #48 in local_import_job: a library symlink
    must only be created when an Image row was actually inserted. The insert is
    on-conflict-do-nothing, so a conflicting insert used to still write a symlink
    for a file the DB does not represent."""

    def _sessions(self, *, insert_returns):
        """Build the three sessions local_import_job opens, with the images
        insert reporting `insert_returns` (None = conflict, int = inserted id)."""
        # session 1: gallery lookup
        s1 = AsyncMock()
        gallery = MagicMock()
        gallery.source = "local"
        gallery.source_id = "guard_test"
        gallery.deleted_at = None
        s1.get = AsyncMock(return_value=gallery)

        # session 2: excluded blobs
        s2 = AsyncMock()
        excl = MagicMock()
        excl.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        s2.execute = AsyncMock(return_value=excl)

        # session 3: main import loop
        s3 = AsyncMock()
        existing = MagicMock()
        existing.all = MagicMock(return_value=[])
        insert_res = MagicMock()
        insert_res.scalar_one_or_none = MagicMock(return_value=insert_returns)
        count_res = MagicMock()
        count_res.scalar_one = MagicMock(return_value=1 if insert_returns else 0)
        effects = [existing, insert_res]
        if insert_returns is not None:
            effects.append(MagicMock())  # blob ref_count UPDATE
        effects.append(count_res)
        s3.execute = AsyncMock(side_effect=effects)
        s3.get = AsyncMock(return_value=MagicMock())
        return s1, s2, s3

    async def _run(self, tmp_path, *, insert_returns):
        from worker.importer import local_import_job

        gallery_dir = _create_test_gallery(tmp_path)
        s1, s2, s3 = self._sessions(insert_returns=insert_returns)
        symlink_spy = AsyncMock()

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_session_rotator([s1, s2, s3])),
            patch("worker.importer._sha256", return_value="cc" * 32),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer.store_blob", AsyncMock(return_value=MagicMock())),
            patch("worker.importer.create_library_symlink", symlink_spy),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", new_callable=AsyncMock),
        ):
            result = await local_import_job(_make_ctx(), source_dir=str(gallery_dir), mode="copy", gallery_id=1)

        return result, symlink_spy

    async def test_insert_conflict_without_image_row_does_not_create_symlink(self, tmp_path):
        """A conflicting images insert (no row created) must not leave a symlink."""
        result, symlink_spy = await self._run(tmp_path, insert_returns=None)

        assert result["status"] == "done"
        symlink_spy.assert_not_called()

    async def test_inserted_image_row_still_creates_symlink(self, tmp_path):
        """Control: a successful insert must keep creating the library symlink."""
        result, symlink_spy = await self._run(tmp_path, insert_returns=42)

        assert result["status"] == "done"
        symlink_spy.assert_called_once()
        assert symlink_spy.call_args.args[:2] == ("local", "guard_test")


# ---------------------------------------------------------------------------
# import_job — duplicate basename disambiguation (edge case #47)
# ---------------------------------------------------------------------------


class TestDisambiguateLibraryFilenames:
    """Unit tests for _disambiguate_library_filenames (edge case #47).

    Library symlinks are keyed by filename only; a recursive import containing
    two files with the same basename in different subdirectories used to let
    the second symlink silently replace the first, while the DB kept two image
    rows — the library dir then exposed only one of them and reconciliation
    could delete the "missing" DB image."""

    def test_unique_names_pass_through(self):
        from worker.importer import _disambiguate_library_filenames

        paths = [Path("/g/001.jpg"), Path("/g/002.jpg")]
        assert _disambiguate_library_filenames(paths) == ["001.jpg", "002.jpg"]

    def test_duplicate_basenames_get_numbered_suffix(self):
        from worker.importer import _disambiguate_library_filenames

        paths = [Path("/g/sub1/001.jpg"), Path("/g/sub2/001.jpg"), Path("/g/sub3/001.jpg")]
        assert _disambiguate_library_filenames(paths) == ["001.jpg", "001__2.jpg", "001__3.jpg"]

    def test_suffix_collision_with_real_filename_skips_taken_name(self):
        from worker.importer import _disambiguate_library_filenames

        # A real file already named 001__2.jpg must not be overwritten by the
        # generated suffix for the second 001.jpg.
        paths = [Path("/g/a/001.jpg"), Path("/g/001__2.jpg"), Path("/g/b/001.jpg")]
        assert _disambiguate_library_filenames(paths) == ["001.jpg", "001__2.jpg", "001__3.jpg"]

    def test_extension_preserved_in_suffix(self):
        from worker.importer import _disambiguate_library_filenames

        paths = [Path("/g/a/x.png"), Path("/g/b/x.png")]
        assert _disambiguate_library_filenames(paths) == ["x.png", "x__2.png"]


class TestImportJobDuplicateBasenames:
    """Wiring test for edge case #47: import_job must give duplicate basenames
    distinct library filenames, used consistently for BOTH the symlink and the
    Image.filename row so disk and DB stay in agreement."""

    async def test_duplicate_basenames_get_distinct_symlinks_and_image_filenames(self, tmp_path):
        from worker.importer import import_job

        gallery_dir = tmp_path / "gallery"
        (gallery_dir / "sub1").mkdir(parents=True)
        (gallery_dir / "sub2").mkdir(parents=True)
        (gallery_dir / "sub1" / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"a")
        (gallery_dir / "sub2" / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"b")
        (gallery_dir / "metadata.json").write_text(json.dumps({"category": "ehentai", "title": "Dup Test", "gid": 777}))

        mock_session = _make_mock_session()
        default_result = mock_session.execute.return_value
        captured_stmts = []

        async def _exec(stmt, *args, **kwargs):
            captured_stmts.append(stmt)
            return default_result

        mock_session.execute = AsyncMock(side_effect=_exec)

        symlink_spy = AsyncMock()
        mock_blob = MagicMock()

        _site_cfg = MagicMock(source_id="ehentai", source_id_fields=("gid",), category="gallery")

        with (
            patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", symlink_spy),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            result = await import_job(_make_ctx(), path=str(gallery_dir), user_id=1)

        assert result["status"] == "done"

        # Both files must get a symlink, with distinct filenames
        names = [c.args[2] for c in symlink_spy.call_args_list]
        assert len(names) == 2, f"expected 2 symlinks, got {names!r}"
        assert len(set(names)) == 2, f"duplicate basenames must be disambiguated, got {names!r}"
        assert "001.jpg" in names

        # The Image rows must use the same disambiguated names
        from sqlalchemy.dialects import postgresql

        img_inserts = [
            s
            for s in captured_stmts
            if getattr(s, "is_insert", False) and getattr(getattr(s, "table", None), "name", None) == "images"
        ]
        assert img_inserts, "images bulk insert not captured"
        params = img_inserts[0].compile(dialect=postgresql.dialect()).params
        db_names = sorted(str(v) for k, v in params.items() if k.startswith("filename"))
        assert db_names == sorted(names), f"DB filenames {db_names!r} must match symlink names {sorted(names)!r}"


# ---------------------------------------------------------------------------
# Disaster-recovery sidecar wiring (info.json)
# ---------------------------------------------------------------------------


class TestImportJobSidecar:
    """import_job must write the info.json disaster-recovery sidecar so a
    gallery recovered from the library tree without the DB stays identifiable."""

    async def test_import_writes_info_json_sidecar_with_gallery_metadata(self, tmp_path):
        from worker.importer import import_job

        gallery_dir = _create_test_gallery(
            tmp_path,
            metadata={
                "category": "ehentai",
                "title": "Test Gallery",
                "tags": {"artist": ["test_artist"]},
                "gid": 12345,
            },
        )

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        _site_cfg = MagicMock(source_id="ehentai", source_id_fields=("gid",), category="gallery")
        sidecar_spy = AsyncMock(return_value=True)

        with (
            patch("worker.importer.AsyncSessionLocal", return_value=_mock_session_ctx(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer.write_gallery_sidecar", sidecar_spy),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._normalize_tags", side_effect=lambda t, s: t),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch(
                "plugins.builtin.gallery_dl._metadata._extract_artist",
                return_value="ehentai:test_artist",
            ),
            patch("worker.importer.rebuild_gallery_tags_array", AsyncMock()),
            patch("worker.importer.upsert_tag_translations", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            result = await import_job(_make_ctx(), path=str(gallery_dir), user_id=1)

        assert result["status"] == "done"
        sidecar_spy.assert_awaited_once()
        source, source_id, payload = sidecar_spy.call_args.args
        assert source == "ehentai"
        assert source_id == "12345"
        assert payload["title"] == "Test Gallery"
        assert "artist:test_artist" in payload["tags"]


class TestLocalImportSidecar:
    """local_import_job must write the info.json sidecar after a successful import."""

    async def test_local_import_writes_info_json_sidecar(self, tmp_path):
        from worker.importer import local_import_job

        gallery_dir = _create_test_gallery(tmp_path)

        s1 = AsyncMock()
        gallery_lookup = MagicMock()
        gallery_lookup.source = "local"
        gallery_lookup.source_id = "sidecar_test"
        gallery_lookup.deleted_at = None
        s1.get = AsyncMock(return_value=gallery_lookup)

        s2 = AsyncMock()
        excl = MagicMock()
        excl.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        s2.execute = AsyncMock(return_value=excl)

        s3 = AsyncMock()
        existing = MagicMock()
        existing.all = MagicMock(return_value=[])
        insert_res = MagicMock()
        insert_res.scalar_one_or_none = MagicMock(return_value=42)
        count_res = MagicMock()
        count_res.scalar_one = MagicMock(return_value=1)
        s3.execute = AsyncMock(side_effect=[existing, insert_res, MagicMock(), count_res])
        s3.get = AsyncMock(return_value=MagicMock())

        sidecar_spy = AsyncMock(return_value=True)

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_session_rotator([s1, s2, s3])),
            patch("worker.importer._sha256", return_value="dd" * 32),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer.store_blob", AsyncMock(return_value=MagicMock())),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer.write_gallery_sidecar", sidecar_spy),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch("core.queue.enqueue", new_callable=AsyncMock),
        ):
            result = await local_import_job(_make_ctx(), source_dir=str(gallery_dir), mode="copy", gallery_id=1)

        assert result["status"] == "done"
        sidecar_spy.assert_awaited_once()
        assert sidecar_spy.call_args.args[:2] == ("local", "sidecar_test")
