"""Tests for services/library_sidecar.py — the info.json disaster-recovery sidecar.

The library symlink tree is the DB-loss escape hatch, but directory names are
source ids: without the DB there is no title/artist/tag information. The
sidecar writes that metadata next to the symlinks so a recovered gallery is
identifiable. It must be best-effort (never fail the job that writes it),
atomic (no truncated JSON), and invisible to reconciliation / the explorer
file listing (covered in their own test files).
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch


def _mock_settings(library):
    s = MagicMock()
    s.data_library_path = str(library)
    return s


def _gallery(**overrides):
    g = MagicMock()
    g.title = "Recovered Title"
    g.title_jpn = None
    g.source = "weibo"
    g.source_id = "12345"
    g.category = "artist_cg"
    g.language = "chinese"
    g.uploader = "someone"
    g.artist_id = "weibo:67890"
    g.pages = 9
    g.source_url = "https://weibo.com/u/67890"
    g.tags_array = ["artist:someone", "general:test"]
    g.posted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    for k, v in overrides.items():
        setattr(g, k, v)
    return g


class TestSidecarPayloadFromGallery:
    def test_payload_contains_identifying_metadata(self):
        from services.library_sidecar import sidecar_payload_from_gallery

        payload = sidecar_payload_from_gallery(_gallery())

        assert payload["title"] == "Recovered Title"
        assert payload["source"] == "weibo"
        assert payload["source_id"] == "12345"
        assert payload["artist_id"] == "weibo:67890"
        assert payload["tags"] == ["artist:someone", "general:test"]
        assert payload["posted_at"] == "2026-01-02T03:04:05+00:00"

    def test_payload_tolerates_empty_optional_fields(self):
        from services.library_sidecar import sidecar_payload_from_gallery

        payload = sidecar_payload_from_gallery(
            _gallery(title=None, tags_array=None, posted_at=None, uploader=None)
        )

        assert payload["title"] is None
        assert payload["tags"] == []
        assert payload["posted_at"] is None


class TestWriteGallerySidecar:
    async def test_sidecar_written_as_valid_json_with_written_at(self, tmp_path):
        from services.library_sidecar import SIDECAR_FILENAME, write_gallery_sidecar

        with patch("services.cas.settings", _mock_settings(tmp_path / "library")):
            ok = await write_gallery_sidecar("weibo", "12345", {"title": "T", "tags": []})

        assert ok is True
        sidecar = tmp_path / "library" / "weibo" / "12345" / SIDECAR_FILENAME
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["title"] == "T"
        assert "written_at" in data

    async def test_sidecar_write_is_atomic_no_temp_litter(self, tmp_path):
        from services.library_sidecar import SIDECAR_FILENAME, write_gallery_sidecar

        with patch("services.cas.settings", _mock_settings(tmp_path / "library")):
            await write_gallery_sidecar("weibo", "12345", {"title": "T"})

        gdir = tmp_path / "library" / "weibo" / "12345"
        assert [p.name for p in gdir.iterdir()] == [SIDECAR_FILENAME]

    async def test_sidecar_overwrites_previous_content(self, tmp_path):
        from services.library_sidecar import SIDECAR_FILENAME, write_gallery_sidecar

        with patch("services.cas.settings", _mock_settings(tmp_path / "library")):
            await write_gallery_sidecar("weibo", "12345", {"title": "Old"})
            await write_gallery_sidecar("weibo", "12345", {"title": "New"})

        sidecar = tmp_path / "library" / "weibo" / "12345" / SIDECAR_FILENAME
        assert json.loads(sidecar.read_text(encoding="utf-8"))["title"] == "New"

    async def test_unserializable_payload_is_swallowed_not_raised(self, tmp_path):
        """The sidecar is a recovery aid: it must never fail the import that
        writes it."""
        from services.library_sidecar import write_gallery_sidecar

        with patch("services.cas.settings", _mock_settings(tmp_path / "library")):
            ok = await write_gallery_sidecar("weibo", "12345", {"bad": object()})

        assert ok is False

    async def test_unwritable_library_root_is_swallowed_not_raised(self):
        from services.library_sidecar import write_gallery_sidecar

        with patch("services.cas.settings", _mock_settings("/proc/definitely/not/writable")):
            ok = await write_gallery_sidecar("weibo", "12345", {"title": "T"})

        assert ok is False
