"""
Unit tests for services/cas.py.

All pure functions are tested in isolation by patching `services.cas.settings`
so no real filesystem layout is required. The async `decrement_ref_count` test
uses an AsyncMock session and verifies `session.execute` is called.
"""

import hashlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select, text

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


class TestLibraryUrl:
    """Unit tests for library_url(external_path) -> str."""

    def test_hash_in_filename_is_percent_encoded_not_left_raw(self):
        """A '#' in the filename must be encoded so the browser doesn't treat it
        as a URL fragment and truncate the <img src> request (the image never
        loads otherwise — ~half the shamakho library filenames carry a '#')."""
        from services.cas import library_url

        ext_path = "/mnt/ssd-data/images/shamakho/2023-05-26-#健全彼女（線ラフver）.jpeg"
        url = library_url(ext_path)

        assert "#" not in url
        assert "%23" in url

    def test_question_mark_in_filename_is_percent_encoded(self):
        """A '?' would otherwise be parsed as the query delimiter."""
        from services.cas import library_url

        url = library_url("/mnt/ssd-data/images/foo/what?.jpeg")

        assert "?" not in url
        assert "%3F" in url

    def test_prefix_and_slashes_preserved(self):
        """The /media/libraries/ prefix and path separators stay literal."""
        from services.cas import library_url

        url = library_url("/mnt/ssd-data/images/foo/bar.jpg")

        assert url == "/media/libraries/ssd-data/images/foo/bar.jpg"

    def test_encoded_url_round_trips_through_unquote_to_media_path(self):
        """media_authz unquotes X-Original-URI and nginx alias decodes for the
        filesystem; unquoting the URL must recover the /media/libraries/ path
        so the external_path ACL lookup still matches."""
        from urllib.parse import unquote

        from services.cas import library_url

        ext_path = "/mnt/ssd-data/images/shamakho/2023-#健全（＋線ラフver）.jpeg"
        url = library_url(ext_path)

        assert unquote(url) == "/media/libraries/ssd-data/images/shamakho/2023-#健全（＋線ラフver）.jpeg"


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

    def test_thumb_url_supports_responsive_width_tiers(self):
        from services.cas import thumb_url

        assert thumb_url(SHA, 360).endswith("/thumb_360.webp")
        assert thumb_url(SHA, 720).endswith("/thumb_720.webp")

    def test_thumb_url_rejects_unknown_tier(self):
        from services.cas import thumb_url

        with pytest.raises(ValueError, match="Unsupported thumbnail size"):
            thumb_url(SHA, 999)

    def test_thumb_srcset_lists_all_static_candidates(self):
        from services.cas import thumb_srcset

        srcset = thumb_srcset(SHA)
        assert "thumb_160.webp 160w" in srcset
        assert "thumb_360.webp 360w" in srcset
        assert "thumb_720.webp 720w" in srcset


# ---------------------------------------------------------------------------
# TestStoreBlobConflict
# ---------------------------------------------------------------------------


class TestStoreBlobConflict:
    """Regression tests for external blob-location upserts (HR-004).

    blobs is keyed by sha256, while external locations are one-to-many. A new
    location must be inserted without overwriting the legacy scalar path, and
    ref_count must not be touched by the blob conflict update.
    """

    async def _capture_upsert_sql(self, tmp_path, *, storage, external_path):
        """Call store_blob with a session that captures the executed statement,
        and return the compiled PostgreSQL SQL string."""
        from sqlalchemy.dialects import postgresql

        from services.cas import store_blob

        f = tmp_path / "img.jpg"
        f.write_bytes(b"data")

        captured = []

        async def fake_execute(stmt):
            captured.append(stmt)
            res = MagicMock()
            res.scalar_one.return_value = MagicMock()
            return res

        session = MagicMock()
        session.execute = fake_execute

        with patch("services.cas.settings", _mock_settings()):
            await store_blob(f, SHA, session, storage=storage, external_path=external_path)

        return [str(stmt.compile(dialect=postgresql.dialect())).lower() for stmt in captured]

    async def test_external_conflict_records_location_without_overwriting_scalar(self, tmp_path):
        sql = await self._capture_upsert_sql(tmp_path, storage="external", external_path="/mnt/new/img.jpg")

        assert len(sql) == 2
        blob_set_clause = sql[0].split("do update set", 1)[1].split("returning", 1)[0]
        assert "external_path" not in blob_set_clause
        assert "insert into blob_locations" in sql[1]
        assert "on conflict (blob_sha256, external_path) do nothing" in sql[1]

    async def test_conflict_never_touches_ref_count(self, tmp_path):
        """The on-conflict update must never write ref_count (would inflate it on
        duplicate re-imports)."""
        sql = await self._capture_upsert_sql(tmp_path, storage="external", external_path="/mnt/new/img.jpg")

        set_clause = sql[0].split("do update set", 1)[1].split("returning", 1)[0]
        assert "ref_count" not in set_clause, f"DO UPDATE SET must not touch ref_count, got: {set_clause!r}"


def test_identical_external_files_keep_independent_image_locations(tmp_path):
    """Removing either same-content source path must not redirect the other image."""
    from db.models import Blob, BlobLocation, Image
    from services.cas import resolve_blob_path

    first_path = tmp_path / "first" / "page.jpg"
    second_path = tmp_path / "second" / "page.jpg"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    payload = b"identical external bytes"
    first_path.write_bytes(payload)
    second_path.write_bytes(payload)
    blob = Blob(
        sha256=SHA,
        file_size=len(payload),
        extension=".jpg",
        storage="external",
        external_path=str(first_path),
    )
    locations = [
        BlobLocation(blob_sha256=SHA, external_path=str(first_path)),
        BlobLocation(blob_sha256=SHA, external_path=str(second_path)),
    ]
    images = [
        Image(blob_sha256=SHA, external_path=str(first_path)),
        Image(blob_sha256=SHA, external_path=str(second_path)),
    ]
    for image in images:
        image.blob = blob

    assert {(location.blob_sha256, location.external_path) for location in locations} == {
        (SHA, str(first_path)),
        (SHA, str(second_path)),
    }

    first_path.unlink()
    assert not resolve_blob_path(images[0].blob, images[0].external_path).exists()
    assert resolve_blob_path(images[1].blob, images[1].external_path).read_bytes() == payload

    first_path.write_bytes(payload)
    second_path.unlink()
    assert resolve_blob_path(images[0].blob, images[0].external_path).read_bytes() == payload
    assert not resolve_blob_path(images[1].blob, images[1].external_path).exists()


async def test_store_blob_persists_multiple_external_locations_and_bindings(db_session, tmp_path):
    from db.models import BlobLocation, Image
    from services.cas import store_blob

    payload = b"shared bytes"
    sha256 = hashlib.sha256(payload).hexdigest()
    paths = [tmp_path / "one" / "page.jpg", tmp_path / "two" / "page.jpg"]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(payload)

    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status, import_mode) VALUES "
            "('local', 'multi-location-a', 'A', 'complete', 'link'), "
            "('local', 'multi-location-b', 'B', 'complete', 'link')"
        )
    )
    gallery_ids = (
        await db_session.execute(
            text(
                "SELECT id FROM galleries "
                "WHERE source_id IN ('multi-location-a', 'multi-location-b') ORDER BY source_id"
            )
        )
    ).scalars().all()

    for gallery_id, path in zip(gallery_ids, paths, strict=True):
        await store_blob(path, sha256, db_session, storage="external", external_path=str(path))
        db_session.add(
            Image(
                gallery_id=gallery_id,
                page_num=1,
                filename=path.name,
                blob_sha256=sha256,
                external_path=str(path),
            )
        )
    await db_session.commit()

    location_count = (
        await db_session.execute(select(func.count()).select_from(BlobLocation).where(BlobLocation.blob_sha256 == sha256))
    ).scalar_one()
    image_paths = set(
        (await db_session.execute(select(Image.external_path).where(Image.blob_sha256 == sha256))).scalars().all()
    )
    assert location_count == 2
    assert image_paths == {str(path) for path in paths}


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
        blob = MagicMock()
        blob.sha256 = SHA
        blob.extension = ".jpg"
        blob.storage = "cas"

        async def fake_execute(_stmt):
            res = MagicMock()
            res.scalar_one.return_value = blob
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


class TestLibraryDirCollisionGuard:
    """Audit #45 / BR-008: safe_source_id() is not injective — 'a/b' and a
    literal 'a__b' both sanitize to 'a__b' — so two distinct galleries could
    silently share one library dir and overwrite each other's symlinks. The
    dir now carries an ownership marker; a mismatch raises loudly."""

    def test_library_dir_collision_between_distinct_source_ids_raises(self, tmp_path):
        import pytest

        from services.cas import LibraryDirCollisionError, ensure_library_dir

        with patch("services.cas.settings", _mock_settings(library=str(tmp_path / "library"))):
            first = ensure_library_dir("ehentai", "a/b")
            assert first.exists()
            with pytest.raises(LibraryDirCollisionError):
                ensure_library_dir("ehentai", "a__b")

    def test_same_gallery_reuse_of_library_dir_does_not_raise(self, tmp_path):
        from services.cas import ensure_library_dir

        with patch("services.cas.settings", _mock_settings(library=str(tmp_path / "library"))):
            first = ensure_library_dir("ehentai", "12345")
            second = ensure_library_dir("ehentai", "12345")
            assert first == second

    def test_pre_marker_library_dir_is_adopted_not_rejected(self, tmp_path):
        """Dirs created before the marker existed must be grandfathered in on
        first touch, not treated as collisions."""
        from services.cas import OWNER_MARKER_FILENAME, ensure_library_dir

        legacy = tmp_path / "library" / "ehentai" / "999"
        legacy.mkdir(parents=True)
        (legacy / "001.jpg").write_bytes(b"x")

        with patch("services.cas.settings", _mock_settings(library=str(tmp_path / "library"))):
            got = ensure_library_dir("ehentai", "999")

        assert got == legacy
        assert (legacy / OWNER_MARKER_FILENAME).read_text(encoding="utf-8") == "ehentai:999"

    async def test_create_library_symlink_collision_raises_and_alerts(self, tmp_path):
        import pytest

        from services.cas import LibraryDirCollisionError, create_library_symlink, ensure_library_dir

        data_root = tmp_path / "data"
        cas_root = data_root / "cas"
        library_root = data_root / "library"
        blob_file = cas_root / SHA[:2] / SHA[2:4] / f"{SHA}.jpg"
        blob_file.parent.mkdir(parents=True)
        blob_file.write_bytes(b"image-bytes")

        blob = MagicMock()
        blob.storage = "cas"
        blob.external_path = None
        blob.sha256 = SHA
        blob.extension = ".jpg"

        alert = AsyncMock()
        with (
            patch("services.cas.settings", _mock_settings(cas=str(cas_root), library=str(library_root))),
            patch("services.cache.push_system_alert", alert),
        ):
            ensure_library_dir("ehentai", "a/b")
            with pytest.raises(LibraryDirCollisionError):
                await create_library_symlink("ehentai", "a__b", "001.jpg", blob)

        alert.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# TestStoreBlobExtensionFirstWins
# ---------------------------------------------------------------------------


class TestStoreBlobExtensionFirstWins:
    """Regression tests for edge case #44: blobs are keyed by sha256 and the
    extension is not updated on conflict, but store_blob() used to write the
    CAS file BEFORE the upsert using the incoming filename's extension — so
    identical bytes arriving as .png after a .jpg import created a second,
    unreferenced CAS file (sha.png) next to the canonical one (sha.jpg).
    The upsert must run first and the filesystem write must use the canonical
    extension from the returned blob row."""

    def _session_returning(self, blob):
        async def fake_execute(_stmt):
            res = MagicMock()
            res.scalar_one.return_value = blob
            return res

        session = MagicMock()
        session.execute = fake_execute
        return session

    def _blob(self, extension):
        blob = MagicMock()
        blob.sha256 = SHA
        blob.extension = extension
        blob.storage = "cas"
        blob.external_path = None
        return blob

    async def test_same_hash_different_extension_does_not_create_second_cas_file(self, tmp_path):
        from services.cas import store_blob

        cas_root = tmp_path / "cas"
        canonical_blob = self._blob(".jpg")

        first = tmp_path / "img.jpg"
        first.write_bytes(b"same-bytes")
        second = tmp_path / "img.png"  # identical content, different extension
        second.write_bytes(b"same-bytes")

        with patch("services.cas.settings", _mock_settings(cas=str(cas_root))):
            await store_blob(first, SHA, self._session_returning(canonical_blob))
            # DB row already exists: the upsert returns the canonical .jpg row
            await store_blob(second, SHA, self._session_returning(canonical_blob))

        blob_dir = cas_root / SHA[:2] / SHA[2:4]
        files = sorted(p.name for p in blob_dir.iterdir())
        assert files == [f"{SHA}.jpg"], f"second extension must not create a second CAS file, got {files}"

    async def test_new_blob_writes_file_with_its_own_extension(self, tmp_path):
        from services.cas import store_blob

        cas_root = tmp_path / "cas"
        fresh_blob = self._blob(".png")

        src = tmp_path / "img.png"
        src.write_bytes(b"fresh")

        with patch("services.cas.settings", _mock_settings(cas=str(cas_root))):
            await store_blob(src, SHA, self._session_returning(fresh_blob))

        assert (cas_root / SHA[:2] / SHA[2:4] / f"{SHA}.png").read_bytes() == b"fresh"
