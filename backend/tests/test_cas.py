"""
Unit tests for services/cas.py.

All pure functions are tested in isolation by patching `services.cas.settings`
so no real filesystem layout is required. The async `decrement_ref_count` test
uses an AsyncMock session and verifies `session.execute` is called.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
# TestStoreBlobConflict
# ---------------------------------------------------------------------------


class TestStoreBlobConflict:
    """Regression tests for store_blob() upsert-on-conflict behaviour (edge case #43).

    blobs is keyed by sha256. For external (link-mode) blobs the on-conflict path
    must REFRESH external_path, otherwise the first path stored for a hash wins
    forever: after the source folder moves, removing + re-importing the gallery
    reuses the surviving blob row and the stale path persists. ref_count must
    still NOT be touched on conflict (duplicate re-imports must not inflate it).
    """

    async def _capture_upsert_sql(self, tmp_path, *, storage, external_path):
        """Call store_blob with a session that captures the executed statement,
        and return the compiled PostgreSQL SQL string."""
        from sqlalchemy.dialects import postgresql

        from services.cas import store_blob

        f = tmp_path / "img.jpg"
        f.write_bytes(b"data")

        captured = {}

        async def fake_execute(stmt):
            captured["stmt"] = stmt
            res = MagicMock()
            res.scalar_one.return_value = MagicMock()
            return res

        session = MagicMock()
        session.execute = fake_execute

        with patch("services.cas.settings", _mock_settings()):
            await store_blob(f, SHA, session, storage=storage, external_path=external_path)

        return str(captured["stmt"].compile(dialect=postgresql.dialect())).lower()

    async def test_external_conflict_refreshes_external_path(self, tmp_path):
        """On conflict, external blobs must update external_path so a re-import
        after the source folder moved heals the stale path."""
        sql = await self._capture_upsert_sql(tmp_path, storage="external", external_path="/mnt/new/img.jpg")

        assert "on conflict" in sql
        set_clause = sql.split("do update set", 1)[1].split("returning", 1)[0]
        assert "external_path" in set_clause, f"DO UPDATE SET must refresh external_path, got: {set_clause!r}"

    async def test_conflict_never_touches_ref_count(self, tmp_path):
        """The on-conflict update must never write ref_count (would inflate it on
        duplicate re-imports)."""
        sql = await self._capture_upsert_sql(tmp_path, storage="external", external_path="/mnt/new/img.jpg")

        set_clause = sql.split("do update set", 1)[1].split("returning", 1)[0]
        assert "ref_count" not in set_clause, f"DO UPDATE SET must not touch ref_count, got: {set_clause!r}"


# ---------------------------------------------------------------------------
# TestStoreBlobConcurrentWrite
# ---------------------------------------------------------------------------


class TestStoreBlobConcurrentWrite:
    """Regression tests for store_blob() concurrent-write behaviour (edge case #41).

    store_blob() checks `dest.exists()` before hardlinking. Two workers importing
    the same new blob can both pass the check; the loser's os.link then raises
    FileExistsError. That must be treated as success (the content-addressed file
    is already in place) — NOT routed into the cross-device copy fallback, which
    would overwrite the winner's file non-atomically while readers may already
    be serving it. The genuine cross-device fallback must promote atomically via
    a temp file + os.replace so no reader ever observes a partial file.
    """

    def _fake_session(self):
        async def fake_execute(_stmt):
            res = MagicMock()
            res.scalar_one.return_value = MagicMock()
            return res

        session = MagicMock()
        session.execute = fake_execute
        return session

    async def test_hardlink_fileexists_race_is_success_without_copy_fallback(self, tmp_path):
        """FileExistsError from os.link (lost race) must be swallowed as success
        and must NOT trigger the copy fallback."""
        from services.cas import store_blob

        src = tmp_path / "img.jpg"
        src.write_bytes(b"data")
        cas_root = tmp_path / "cas"

        with (
            patch("services.cas.settings", _mock_settings(cas=str(cas_root))),
            patch("services.cas.os.link", side_effect=FileExistsError) as link_mock,
            patch("services.cas.shutil.copy2") as copy_mock,
        ):
            await store_blob(src, SHA, self._fake_session())

        link_mock.assert_called_once()
        copy_mock.assert_not_called()

    async def test_cross_device_fallback_copies_to_temp_then_atomic_replace(self, tmp_path):
        """A real cross-device fallback (EXDEV) must copy to a temp file and
        atomically promote it, never copying onto the final destination directly."""
        import errno
        import shutil as real_shutil

        from services.cas import store_blob

        src = tmp_path / "img.jpg"
        src.write_bytes(b"data")
        cas_root = tmp_path / "cas"

        copy_targets: list[str] = []
        real_copy2 = real_shutil.copy2  # bind before patching, or the spy recurses into the mock

        def spy_copy2(s, d):
            copy_targets.append(str(d))
            return real_copy2(s, d)

        with (
            patch("services.cas.settings", _mock_settings(cas=str(cas_root))),
            patch("services.cas.os.link", side_effect=OSError(errno.EXDEV, "cross-device link")),
            patch("services.cas.shutil.copy2", side_effect=spy_copy2),
        ):
            await store_blob(src, SHA, self._fake_session())

        dest = cas_root / SHA[:2] / SHA[2:4] / f"{SHA}.jpg"
        assert dest.read_bytes() == b"data"
        # copy2 must never target the final CAS path directly (non-atomic window)
        assert copy_targets, "copy fallback must have been used"
        assert all(t != str(dest) for t in copy_targets), (
            f"copy2 wrote directly to the final destination: {copy_targets!r}"
        )
        # no temp litter left behind
        leftovers = [p for p in dest.parent.iterdir() if p != dest]
        assert leftovers == [], f"temp files left in CAS dir: {leftovers!r}"


# ---------------------------------------------------------------------------
# TestCreateLibrarySymlink
# ---------------------------------------------------------------------------


class TestCreateLibrarySymlink:
    """Regression tests for create_library_symlink(source, source_id, filename, blob).

    The library symlink tree under /data/library is browsed by users outside the
    container (host file browser / Samba), where the /data volume is mounted at a
    different absolute path (e.g. ${JYZROX_DATA_ROOT}/data). CAS-backed symlinks
    that stored an absolute /data/cas/... target therefore appeared as broken
    symlinks on the host. CAS links must be RELATIVE so they resolve regardless
    of the volume's mount point; external links stay absolute (identical bind mount).
    """

    def _make_cas_blob(self, sha256=SHA, extension=".jpg"):
        blob = MagicMock()
        blob.storage = "cas"
        blob.external_path = None
        blob.sha256 = sha256
        blob.extension = extension
        return blob

    async def test_cas_symlink_is_relative_and_survives_volume_remount(self, tmp_path):
        """A CAS symlink must use a relative target so it still resolves when the
        data volume is mounted at a different absolute path (container vs host)."""
        from services.cas import create_library_symlink

        data_root = tmp_path / "data"
        cas_root = data_root / "cas"
        library_root = data_root / "library"

        blob_file = cas_root / SHA[:2] / SHA[2:4] / f"{SHA}.jpg"
        blob_file.parent.mkdir(parents=True)
        blob_file.write_bytes(b"image-bytes")

        blob = self._make_cas_blob()
        with patch("services.cas.settings", _mock_settings(cas=str(cas_root), library=str(library_root))):
            await create_library_symlink("ehentai", "12345", "001.jpg", blob)

        link = library_root / "ehentai" / "12345" / "001.jpg"
        assert link.is_symlink()
        # The whole point: the target must NOT be an absolute /data/... path.
        target = os.readlink(link)
        assert not os.path.isabs(target), f"CAS symlink target must be relative, got {target!r}"
        assert link.resolve().read_bytes() == b"image-bytes"

        # Simulate the volume being mounted at a different absolute path by moving
        # the entire data root. An absolute symlink would now dangle; a relative
        # one keeps resolving because library/ and cas/ moved together.
        remounted = tmp_path / "host_mountpoint"
        data_root.rename(remounted)
        moved_link = remounted / "library" / "ehentai" / "12345" / "001.jpg"
        assert moved_link.resolve().exists(), "relative CAS symlink must survive a mount-point change"
        assert moved_link.resolve().read_bytes() == b"image-bytes"

    async def test_external_symlink_stays_absolute(self, tmp_path):
        """External (link-mode) blobs live outside the data volume and rely on an
        identical bind-mount path, so their symlink target stays absolute."""
        from services.cas import create_library_symlink

        library_root = tmp_path / "data" / "library"
        ext_file = tmp_path / "mnt" / "images" / "pic.jpg"
        ext_file.parent.mkdir(parents=True)
        ext_file.write_bytes(b"x")

        blob = MagicMock()
        blob.storage = "external"
        blob.external_path = str(ext_file)
        blob.sha256 = SHA
        blob.extension = ".jpg"

        with patch("services.cas.settings", _mock_settings(library=str(library_root))):
            await create_library_symlink("local", "art/title", "pic.jpg", blob)

        link = library_root / "local" / "art__title" / "pic.jpg"
        assert link.is_symlink()
        assert os.readlink(link) == str(ext_file)


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
