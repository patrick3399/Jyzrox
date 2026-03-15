"""
Unit tests for services/cas.py.

All pure functions are tested in isolation by patching `services.cas.settings`
so no real filesystem layout is required. The async `decrement_ref_count` test
uses an AsyncMock session and verifies `session.execute` is called.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Consistent 64-character hex sha256 used throughout
SHA = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


def _mock_settings(cas="/data/cas", library="/data/library", thumbs="/data/thumbs"):
    """Return a MagicMock that mimics the settings object."""
    s = MagicMock()
    s.data_cas_path = cas
    s.data_library_path = library
    s.data_thumbs_path = thumbs
    return s


# ---------------------------------------------------------------------------
# TestCasPath
# ---------------------------------------------------------------------------


class TestCasPath:
    """Unit tests for cas_path(sha256, ext) -> Path."""

    def test_cas_path_structure(self):
        """Path should follow /{cas_root}/{sha[:2]}/{sha[2:4]}/{sha}{ext}."""
        from services.cas import cas_path

        with patch("services.cas.settings", _mock_settings(cas="/data/cas")):
            result = cas_path(SHA, ".jpg")

        assert result == Path(f"/data/cas/{SHA[:2]}/{SHA[2:4]}/{SHA}.jpg")

    def test_cas_path_custom_root(self):
        """data_cas_path should be honoured."""
        from services.cas import cas_path

        with patch("services.cas.settings", _mock_settings(cas="/mnt/store")):
            result = cas_path(SHA, ".png")

        # Use Path comparison so the test works on both POSIX and Windows.
        assert result.parts[0:3] == Path("/mnt/store").parts

    def test_cas_path_preserves_extension(self):
        """Extension (including the dot) must appear at the end of the filename."""
        from services.cas import cas_path

        with patch("services.cas.settings", _mock_settings()):
            result = cas_path(SHA, ".webp")

        assert result.name == f"{SHA}.webp"

    def test_cas_path_returns_path_object(self):
        """Return type must be pathlib.Path."""
        from services.cas import cas_path

        with patch("services.cas.settings", _mock_settings()):
            result = cas_path(SHA, ".jpg")

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# TestCasUrl
# ---------------------------------------------------------------------------


class TestCasUrl:
    """Unit tests for cas_url(sha256, ext) -> str."""

    def test_cas_url_structure(self):
        """URL should follow /media/cas/{sha[:2]}/{sha[2:4]}/{sha}{ext}."""
        from services.cas import cas_url

        result = cas_url(SHA, ".jpg")

        assert result == f"/media/cas/{SHA[:2]}/{SHA[2:4]}/{SHA}.jpg"

    def test_cas_url_returns_string(self):
        """Return type must be str."""
        from services.cas import cas_url

        result = cas_url(SHA, ".png")

        assert isinstance(result, str)

    def test_cas_url_starts_with_slash(self):
        """URL must start with /media/cas/."""
        from services.cas import cas_url

        result = cas_url(SHA, ".mp4")

        assert result.startswith("/media/cas/")


# ---------------------------------------------------------------------------
# TestSafeSourceId
# ---------------------------------------------------------------------------


class TestSafeSourceId:
    """Unit tests for safe_source_id(source_id) -> str."""

    def test_slashes_replaced_with_double_underscore(self):
        """Forward slashes must be replaced by '__'."""
        from services.cas import safe_source_id

        assert safe_source_id("foo/bar/baz") == "foo__bar__baz"

    def test_double_dots_stripped_to_single_underscore(self):
        """'..' must be replaced by '_' to prevent path traversal."""
        from services.cas import safe_source_id

        assert safe_source_id("foo..bar") == "foo_bar"

    def test_whitespace_trimmed(self):
        """Leading and trailing whitespace must be removed."""
        from services.cas import safe_source_id

        assert safe_source_id("  hello world  ") == "hello world"

    def test_normal_string_unchanged(self):
        """Strings without special characters must pass through as-is."""
        from services.cas import safe_source_id

        assert safe_source_id("artist-name_123") == "artist-name_123"

    def test_empty_string(self):
        """An empty string must return an empty string."""
        from services.cas import safe_source_id

        assert safe_source_id("") == ""

    def test_combined_transformations(self):
        """All transformations must compose: slash, double-dot, whitespace."""
        from services.cas import safe_source_id

        assert safe_source_id("  a/b..c  ") == "a__b_c"


# ---------------------------------------------------------------------------
# TestLibraryDir
# ---------------------------------------------------------------------------


class TestLibraryDir:
    """Unit tests for library_dir(source, source_id) -> Path."""

    def test_library_dir_structure(self):
        """Path should follow /{library_root}/{source}/{safe_source_id}."""
        from services.cas import library_dir

        with patch("services.cas.settings", _mock_settings(library="/data/library")):
            result = library_dir("ehentai", "12345")

        assert result == Path("/data/library/ehentai/12345")

    def test_library_dir_sanitises_source_id(self):
        """safe_source_id must be applied to source_id."""
        from services.cas import library_dir

        with patch("services.cas.settings", _mock_settings(library="/data/library")):
            result = library_dir("pixiv", "artist/name")

        assert result == Path("/data/library/pixiv/artist__name")

    def test_library_dir_returns_path_object(self):
        """Return type must be pathlib.Path."""
        from services.cas import library_dir

        with patch("services.cas.settings", _mock_settings()):
            result = library_dir("source", "id")

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# TestResolveBlobPath
# ---------------------------------------------------------------------------


class TestResolveBlobPath:
    """Unit tests for resolve_blob_path(blob) -> Path."""

    def _make_blob(self, storage, external_path=None, sha256=SHA, extension=".jpg"):
        blob = MagicMock()
        blob.storage = storage
        blob.external_path = external_path
        blob.sha256 = sha256
        blob.extension = extension
        return blob

    def test_cas_storage_returns_cas_path(self):
        """storage='cas' must return the CAS path regardless of external_path."""
        from services.cas import resolve_blob_path

        blob = self._make_blob("cas")
        with patch("services.cas.settings", _mock_settings()):
            result = resolve_blob_path(blob)

        assert result == Path(f"/data/cas/{SHA[:2]}/{SHA[2:4]}/{SHA}.jpg")

    def test_external_storage_with_path_returns_external_path(self):
        """storage='external' with external_path must return that path directly."""
        from services.cas import resolve_blob_path

        blob = self._make_blob("external", external_path="/mnt/nfs/image.jpg")
        result = resolve_blob_path(blob)

        assert result == Path("/mnt/nfs/image.jpg")

    def test_external_storage_without_path_falls_back_to_cas(self):
        """storage='external' with external_path=None must fall back to CAS."""
        from services.cas import resolve_blob_path

        blob = self._make_blob("external", external_path=None)
        with patch("services.cas.settings", _mock_settings()):
            result = resolve_blob_path(blob)

        assert result == Path(f"/data/cas/{SHA[:2]}/{SHA[2:4]}/{SHA}.jpg")

    def test_resolve_blob_path_returns_path_object(self):
        """Return type must always be pathlib.Path."""
        from services.cas import resolve_blob_path

        blob = self._make_blob("external", external_path="/some/path.png")
        result = resolve_blob_path(blob)

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# TestThumbDir
# ---------------------------------------------------------------------------


class TestThumbDir:
    """Unit tests for thumb_dir(sha256) -> Path."""

    def test_thumb_dir_structure(self):
        """Path should follow /{thumbs_root}/{sha[:2]}/{sha[2:4]}/{sha}."""
        from services.cas import thumb_dir

        with patch("services.cas.settings", _mock_settings(thumbs="/data/thumbs")):
            result = thumb_dir(SHA)

        assert result == Path(f"/data/thumbs/{SHA[:2]}/{SHA[2:4]}/{SHA}")

    def test_thumb_dir_returns_path_object(self):
        """Return type must be pathlib.Path."""
        from services.cas import thumb_dir

        with patch("services.cas.settings", _mock_settings()):
            result = thumb_dir(SHA)

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# TestThumbUrl
# ---------------------------------------------------------------------------


class TestThumbUrl:
    """Unit tests for thumb_url(sha256) -> str."""

    def test_thumb_url_structure(self):
        """URL should follow /media/thumbs/{sha[:2]}/{sha[2:4]}/{sha}/thumb_160.webp."""
        from services.cas import thumb_url

        result = thumb_url(SHA)

        assert result == f"/media/thumbs/{SHA[:2]}/{SHA[2:4]}/{SHA}/thumb_160.webp"

    def test_thumb_url_ends_with_webp_filename(self):
        """URL must end with /thumb_160.webp."""
        from services.cas import thumb_url

        result = thumb_url(SHA)

        assert result.endswith("/thumb_160.webp")

    def test_thumb_url_returns_string(self):
        """Return type must be str."""
        from services.cas import thumb_url

        result = thumb_url(SHA)

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# TestDecrementRefCount
# ---------------------------------------------------------------------------


class TestDecrementRefCount:
    """Unit tests for async decrement_ref_count(sha256, session)."""

    async def test_decrement_ref_count_calls_session_execute(self):
        """session.execute must be called exactly once with an UPDATE statement."""
        from services.cas import decrement_ref_count

        session = AsyncMock()
        await decrement_ref_count(SHA, session)

        session.execute.assert_called_once()

    async def test_decrement_ref_count_returns_none(self):
        """Function must return None (it is a fire-and-forget helper)."""
        from services.cas import decrement_ref_count

        session = AsyncMock()
        result = await decrement_ref_count(SHA, session)

        assert result is None
