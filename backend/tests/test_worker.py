"""
Unit tests for pure helper functions in worker.py.

No HTTP client or database fixtures are required — these functions are
imported directly from the worker module and tested in isolation.
"""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _detect_source
# ---------------------------------------------------------------------------


class TestWorkerDetectSource:
    """Unit tests for core.utils.detect_source (plugin-based detection)."""

    def test_ehentai_org_url(self):
        """e-hentai.org URLs must return 'ehentai'."""
        from core.utils import detect_source

        assert detect_source("https://e-hentai.org/g/123456/abcdef/") == "ehentai"

    def test_exhentai_org_url(self):
        """exhentai.org URLs must return 'ehentai'."""
        from core.utils import detect_source

        assert detect_source("https://exhentai.org/g/654321/fedcba/") == "ehentai"

    def test_pixiv_net_url_returns_hostname(self):
        """pixiv.net URLs must return 'pixiv' source_id."""
        from core.utils import detect_source

        result = detect_source("https://www.pixiv.net/artworks/12345")
        assert result == "pixiv"

    def test_unknown_domain_returns_hostname(self):
        """Unrecognised URLs should return 'unknown'."""
        from core.utils import detect_source

        result = detect_source("https://example.com/gallery/1")
        assert result == "unknown"

    def test_invalid_url_returns_other(self):
        """A completely unparseable string must return 'unknown'."""
        from core.utils import detect_source

        result = detect_source("not-a-url-at-all")
        assert result == "unknown"

    def test_bare_domain_returns_hostname(self):
        """URL with a registered plugin domain must return the plugin source id."""
        from core.utils import detect_source

        # danbooru is a registered plugin source in the test environment
        result = detect_source("https://danbooru.donmai.us/posts/1")
        assert result == "danbooru"


# ---------------------------------------------------------------------------
# _extract_tags
# ---------------------------------------------------------------------------


class TestWorkerExtractTags:
    """Unit tests for worker._extract_tags."""

    def test_extract_tags_from_dict_metadata(self, tmp_path: Path):
        """Tags as a dict (EH format) → 'namespace:name' strings."""
        from worker import _extract_tags

        metadata = {
            "tags": {
                "artist": ["creator_a", "creator_b"],
                "character": ["char_x"],
            }
        }
        tags = _extract_tags(tmp_path, metadata)
        assert "artist:creator_a" in tags
        assert "artist:creator_b" in tags
        assert "character:char_x" in tags
        assert len(tags) == 3

    def test_extract_tags_from_list_metadata(self, tmp_path: Path):
        """Tags as a plain list → returned unchanged."""
        from worker import _extract_tags

        metadata = {"tags": ["general:safe", "artist:someone", "rating:explicit"]}
        tags = _extract_tags(tmp_path, metadata)
        assert tags == ["general:safe", "artist:someone", "rating:explicit"]

    def test_extract_tags_empty_metadata_falls_back_to_tags_txt(self, tmp_path: Path):
        """When metadata has no tags, fall back to tags.txt in the directory."""
        from worker import _extract_tags

        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("artist:fallback_artist\ncharacter:fallback_char\n")

        tags = _extract_tags(tmp_path, {})
        assert "artist:fallback_artist" in tags
        assert "character:fallback_char" in tags

    def test_extract_tags_empty_metadata_no_tags_txt(self, tmp_path: Path):
        """No metadata tags and no tags.txt → empty list."""
        from worker import _extract_tags

        tags = _extract_tags(tmp_path, {})
        assert tags == []

    def test_extract_tags_tags_txt_strips_blank_lines(self, tmp_path: Path):
        """Blank lines in tags.txt must be ignored."""
        from worker import _extract_tags

        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("artist:clean\n\n   \ncharacter:also_clean\n")

        tags = _extract_tags(tmp_path, {})
        assert "" not in tags
        assert "   " not in tags
        assert "artist:clean" in tags
        assert "character:also_clean" in tags

    def test_extract_tags_metadata_takes_priority_over_tags_txt(self, tmp_path: Path):
        """When metadata has tags, tags.txt must be ignored."""
        from worker import _extract_tags

        tags_file = tmp_path / "tags.txt"
        tags_file.write_text("artist:should_not_appear\n")

        metadata = {"tags": ["artist:from_metadata"]}
        tags = _extract_tags(tmp_path, metadata)
        assert "artist:from_metadata" in tags
        assert "artist:should_not_appear" not in tags


# ---------------------------------------------------------------------------
# _build_gallery
# ---------------------------------------------------------------------------


class TestWorkerBuildGallery:
    """Unit tests for worker._build_gallery."""

    def test_build_gallery_basic_fields(self):
        """All required keys must be present in the returned dict."""
        from worker import _build_gallery

        meta = {
            "title": "Test Title",
            "title_jpn": "テスト",
            "category": "Doujinshi",
            "lang": "english",
            "uploader": "some_uploader",
        }
        result = _build_gallery("ehentai", "12345", meta, ["artist:foo"], 20)

        assert result["source"] == "ehentai"
        assert result["source_id"] == "12345"
        assert result["title"] == "Test Title"
        assert result["title_jpn"] == "テスト"
        assert result["category"] == "Doujinshi"
        assert result["language"] == "english"
        assert result["pages"] == 20
        assert result["uploader"] == "some_uploader"
        assert result["download_status"] == "complete"
        assert result["tags_array"] == ["artist:foo"]

    def test_build_gallery_unix_timestamp_date(self):
        """Integer 'date' field must be parsed to a datetime."""
        from datetime import datetime

        from worker import _build_gallery

        result = _build_gallery("pixiv", "999", {"date": 1700000000}, [], 5)
        assert isinstance(result["posted_at"], datetime)

    def test_build_gallery_iso_string_date(self):
        """ISO-format 'date' field must be parsed correctly."""
        from datetime import datetime

        from worker import _build_gallery

        result = _build_gallery("pixiv", "998", {"date": "2024-01-15T12:00:00"}, [], 1)
        assert isinstance(result["posted_at"], datetime)
        assert result["posted_at"].year == 2024

    def test_build_gallery_no_date(self):
        """Missing date → posted_at must be None."""
        from worker import _build_gallery

        result = _build_gallery("ehentai", "997", {}, [], 10)
        assert result["posted_at"] is None

    def test_build_gallery_invalid_date_graceful(self):
        """Unparseable date must not raise — posted_at should be None."""
        from worker import _build_gallery

        result = _build_gallery("ehentai", "996", {"date": "not-a-date"}, [], 3)
        assert result["posted_at"] is None

    def test_build_gallery_falls_back_to_title_en(self):
        """'title_en' in metadata is used when 'title' is absent."""
        from worker import _build_gallery

        meta = {"title_en": "English Title"}
        result = _build_gallery("ehentai", "995", meta, [], 1)
        assert result["title"] == "English Title"

    def test_build_gallery_posted_field_alias(self):
        """'posted' field is accepted as a date alias."""
        from datetime import datetime

        from worker import _build_gallery

        result = _build_gallery("ehentai", "994", {"posted": 1700000000}, [], 1)
        assert isinstance(result["posted_at"], datetime)

    def test_build_gallery_empty_tags(self):
        """Empty tags list is stored as an empty list, not None."""
        from worker import _build_gallery

        result = _build_gallery("ehentai", "993", {}, [], 1)
        assert result["tags_array"] == []


# ---------------------------------------------------------------------------
# _sha256
# ---------------------------------------------------------------------------


class TestWorkerSha256:
    """Unit tests for worker._sha256."""

    def test_sha256_matches_hashlib(self):
        """_sha256 must return the same digest as hashlib for the same file."""
        from worker import _sha256

        content = b"Hello, Jyzrox! This is a test file for SHA-256 hashing."
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)

        try:
            expected = hashlib.sha256(content).hexdigest()
            result = _sha256(tmp_path)
            assert result == expected
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_sha256_empty_file(self):
        """Empty file must return the standard SHA-256 of zero bytes."""
        from worker import _sha256

        expected = hashlib.sha256(b"").hexdigest()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = Path(f.name)

        try:
            result = _sha256(tmp_path)
            assert result == expected
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_sha256_large_file(self):
        """_sha256 must handle files larger than a single read chunk (64 KiB)."""
        from worker import _sha256

        content = os.urandom(200_000)  # 200 KB — forces two+ read iterations
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)

        try:
            expected = hashlib.sha256(content).hexdigest()
            result = _sha256(tmp_path)
            assert result == expected
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_sha256_different_content_different_hash(self):
        """Two files with different content must produce different hashes."""
        from worker import _sha256

        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b"content_alpha")
            p1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b"content_beta")
            p2 = Path(f2.name)

        try:
            assert _sha256(p1) != _sha256(p2)
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Pixiv tag processing — importer._extract_tags with namespaced auto-tags
# ---------------------------------------------------------------------------


class TestPixivTagProcessing:
    """Verify importer._extract_tags preserves namespaced auto-tag format."""

    def test_extract_tags_with_namespaced_auto_tags(self, tmp_path: Path):
        """Tags already in namespace:name format pass through unchanged."""
        from worker.importer import _extract_tags

        metadata = {"tags": ["landscape", "rating:r18", "meta:manga"]}
        tags = _extract_tags(tmp_path, metadata)
        assert "landscape" in tags
        assert "rating:r18" in tags
        assert "meta:manga" in tags

    def test_extract_tags_list_with_mixed_namespaces(self, tmp_path: Path):
        """Mixed namespaced and bare tags are all preserved in the output list."""
        from worker.importer import _extract_tags

        metadata = {"tags": ["general:tree", "rating:safe", "bare_tag"]}
        tags = _extract_tags(tmp_path, metadata)
        assert "general:tree" in tags
        assert "rating:safe" in tags
        assert "bare_tag" in tags
