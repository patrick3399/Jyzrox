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

import pytest

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
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute = AsyncMock(return_value=result)
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
            patch("worker.importer.settings", MagicMock(tag_model_enabled=False)),
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
            patch("worker.importer.settings", MagicMock(tag_model_enabled=False)),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            ctx = _make_ctx()
            await import_job(ctx, path=str(gallery_dir))

        mock_enqueue.assert_any_call("thumbnail_job", gallery_id=1)

    async def test_tag_job_enqueued_when_tag_model_enabled(self, tmp_path):
        """When tag_model_enabled=True, tag_job must be enqueued after import."""
        from worker.importer import import_job

        gallery_dir = _create_test_gallery(
            tmp_path,
            metadata={"category": "ehentai", "title": "T", "gid": 42},
        )

        mock_session = _make_mock_session()
        mock_blob = MagicMock()
        mock_blob.sha256 = "ff" * 32

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
            patch("worker.helpers._sha256", return_value="bb" * 32),
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
            # tag_model_enabled = True
            patch("worker.importer.settings", MagicMock(tag_model_enabled=True)),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            ctx = _make_ctx()
            await import_job(ctx, path=str(gallery_dir))

        enqueued_calls = [c.args[0] for c in mock_enqueue.call_args_list]
        assert "tag_job" in enqueued_calls

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
            patch("worker.importer.settings", MagicMock(tag_model_enabled=False)),
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
            patch("worker.importer.settings", MagicMock(tag_model_enabled=False)),
        ):
            ctx = _make_ctx()
            result = await import_job(ctx, path=str(gallery_dir))

        assert result["status"] == "done"
