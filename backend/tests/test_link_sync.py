"""Link gallery sync against a real folder and the test DB (ADR 0015: register first, hash later)."""

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

JPEG = b"\xff\xd8\xff\xe0"


def _write(path: Path, payload: bytes, *, age_s: int = 60) -> None:
    """Write a file and backdate it so it counts as settled."""
    path.write_bytes(JPEG + payload)
    stamp = time.time_ns() - age_s * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


async def _gallery(db_session, source: Path, root: Path, *, status: str = "complete") -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, library_path, "
            "download_status) VALUES ('local', :sid, 'T', 'link', :path, :root, :status)"
        ),
        {"sid": source.name, "path": str(source), "root": str(root), "status": status},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": source.name})
    ).scalar_one()


async def _images(db_session, gallery_id: int) -> list[tuple]:
    """(id, filename, external_path, blob_sha256, page_num, source_size) per page."""
    rows = await db_session.execute(
        text(
            "SELECT id, filename, external_path, blob_sha256, page_num, source_size FROM images "
            "WHERE gallery_id=:gid ORDER BY page_num"
        ),
        {"gid": gallery_id},
    )
    return [tuple(row) for row in rows.all()]


async def _attach_blob(db_session, image_id: int, sha: str, path: str, *, ref_count: int = 1) -> None:
    """Give a pending page a blob + location, as a finished hash pass would."""
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, external_path, ref_count) "
            "VALUES (:sha, 1, 'image', '.jpg', 'external', :path, :rc)"
        ),
        {"sha": sha, "path": path, "rc": ref_count},
    )
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
        {"sha": sha, "path": path},
    )
    await db_session.execute(
        text("UPDATE images SET blob_sha256=:sha WHERE id=:id"),
        {"sha": sha, "id": image_id},
    )
    await db_session.commit()


@contextmanager
def _env(db_session_factory, library_root: Path):
    cas_settings = MagicMock()
    cas_settings.data_library_path = str(library_root)
    hasher = MagicMock(side_effect=AssertionError("sync must not hash"))
    with (
        patch("services.link_sync.AsyncSessionLocal", db_session_factory),
        patch("services.cas.settings", cas_settings),
        patch("services.link_sync.emit_safe", new_callable=AsyncMock),
        patch("services.link_sync.write_gallery_sidecar", new_callable=AsyncMock),
        patch("services.link_sync.cleanup_unreferenced_thumbnails", new_callable=AsyncMock, return_value=set()),
        # create=True: the hash pass (and its import) arrives with the background job.
        patch("services.link_sync.hash_file_with_identity", hasher, create=True),
        patch("core.queue.enqueue", new_callable=AsyncMock) as enqueue,
    ):
        enqueue.hasher = hasher
        yield enqueue


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "lib"
    source = root / "g1"
    source.mkdir(parents=True)
    return root, source, tmp_path / "library"


async def test_sync_registers_new_files_as_pending_without_hashing(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"two")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library) as enqueue:
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.status, result.added, result.pending, result.pages) == ("synced", 2, 2, 2)
    rows = await _images(db_session, gallery_id)
    assert [row[1] for row in rows] == ["001.jpg", "002.jpg"]
    assert all(row[3] is None for row in rows), "pages must be pending (no blob)"
    assert [row[5] for row in rows] == [(source / "001.jpg").stat().st_size, (source / "002.jpg").stat().st_size]
    for name in ("001.jpg", "002.jpg"):
        link = library / "local" / "g1" / name
        assert link.is_symlink()
        assert link.resolve() == (source / name).resolve()
    assert (await db_session.execute(text("SELECT COUNT(*) FROM blobs"))).scalar_one() == 0
    enqueue.hasher.assert_not_called()
    enqueue.assert_awaited()
    call = enqueue.await_args
    assert call.args == ("link_hash_job",)
    assert call.kwargs["gallery_id"] == gallery_id
    assert call.kwargs["_job_id"] == f"link-hash:{gallery_id}"


async def test_sync_unchanged_directory_mtime_skips_listing(db_session, db_session_factory, mock_redis, layout):
    from services import link_sync

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library) as enqueue:
        first = await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)
        with patch("services.link_sync.scan_media_files", wraps=link_sync.scan_media_files) as scan:
            second = await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)

    assert (first.status, first.added, first.pages) == ("synced", 1, 1)
    assert second.status == "unchanged"
    assert (second.pages, second.pending) == (1, 1)
    scan.assert_not_called()
    # Pages are still pending, so the unchanged path keeps the hash job alive.
    assert [call.args[0] for call in enqueue.await_args_list] == ["link_hash_job", "link_hash_job"]


async def test_sync_renamed_file_keeps_image_id_by_fingerprint(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        before = await _images(db_session, gallery_id)
        (source / "001.jpg").rename(source / "cover.jpg")
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    after = await _images(db_session, gallery_id)
    assert (result.renamed, result.added, result.removed) == (1, 0, 0)
    assert len(after) == 1
    assert after[0][0] == before[0][0], "a rename must not replace the Image row"
    assert after[0][1:3] == ("cover.jpg", str(source / "cover.jpg"))
    assert (library / "local" / "g1" / "cover.jpg").is_symlink()
    assert not (library / "local" / "g1" / "001.jpg").is_symlink()


async def test_sync_renamed_hashed_file_keeps_its_blob(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)
    sha = "b" * 64

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        image_id = (await _images(db_session, gallery_id))[0][0]
        await _attach_blob(db_session, image_id, sha, str(source / "001.jpg"))
        (source / "001.jpg").rename(source / "cover.jpg")
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    after = await _images(db_session, gallery_id)
    assert result.renamed == 1
    assert [(row[0], row[2], row[3]) for row in after] == [(image_id, str(source / "cover.jpg"), sha)]
    locations = (
        (
            await db_session.execute(
                text("SELECT external_path FROM blob_locations WHERE blob_sha256=:sha"), {"sha": sha}
            )
        )
        .scalars()
        .all()
    )
    assert str(source / "cover.jpg") in locations


async def test_sync_changed_file_is_reset_to_pending_and_releases_its_blob(
    db_session, db_session_factory, mock_redis, layout
):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"original")
    gallery_id = await _gallery(db_session, source, root)
    sha = "c" * 64

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        before = (await _images(db_session, gallery_id))[0]
        await _attach_blob(db_session, before[0], sha, str(source / "001.jpg"), ref_count=1)
        _write(source / "001.jpg", b"edited-and-longer", age_s=30)
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    after = await _images(db_session, gallery_id)
    assert result.replaced == 1
    assert len(after) == 1, "an in-place overwrite must not add a second page"
    assert after[0][0] == before[0]
    assert after[0][3] is None
    assert after[0][5] == (source / "001.jpg").stat().st_size != before[5]
    ref_count = (
        await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256=:sha"), {"sha": sha})
    ).scalar_one()
    assert ref_count == 0


async def test_sync_deleted_file_removes_row_and_symlink(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"two")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        (source / "002.jpg").unlink()
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.removed, result.pages) == (1, 1)
    assert [row[1] for row in await _images(db_session, gallery_id)] == ["001.jpg"]
    assert not (library / "local" / "g1" / "002.jpg").is_symlink()


@pytest.mark.parametrize("unmount", ["absent", "empty"])
async def test_sync_unavailable_library_root_removes_nothing(
    db_session, db_session_factory, mock_redis, layout, tmp_path, unmount
):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        root.rename(tmp_path / "elsewhere")
        if unmount == "empty":
            root.mkdir()
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    assert result.status == "root_unavailable"
    assert len(await _images(db_session, gallery_id)) == 1


async def test_sync_trashed_gallery_is_not_mutated(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)
    await db_session.execute(
        text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id=:gid"), {"gid": gallery_id}
    )
    await db_session.commit()

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    assert result.status == "skipped_trashed"
    assert await _images(db_session, gallery_id) == []


async def test_sync_file_still_being_written_is_left_for_the_next_sync(
    db_session, db_session_factory, mock_redis, layout
):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "copying.jpg", b"partial", age_s=0)
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.status, result.added) == ("synced", 0)
    dir_mtime = (
        await db_session.execute(text("SELECT source_dir_mtime_ns FROM galleries WHERE id=:gid"), {"gid": gallery_id})
    ).scalar_one()
    assert dir_mtime is None, "an unsettled file must force a full diff next time"


async def test_sync_invalid_image_magic_is_not_registered(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "fake.png", b"jpeg-bytes-under-a-png-name")  # JPEG magic, .png extension
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.status, result.added) == ("synced", 0)
    assert await _images(db_session, gallery_id) == []


async def test_sync_held_lock_returns_busy(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)
    mock_redis.set = AsyncMock(return_value=None)

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert result.status == "busy"
    assert await _images(db_session, gallery_id) == []


async def test_sync_importing_gallery_is_registered_immediately(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root, status="importing")

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.status, result.added) == ("synced", 1)
    status = (
        await db_session.execute(text("SELECT download_status FROM galleries WHERE id=:gid"), {"gid": gallery_id})
    ).scalar_one()
    assert status == "importing", "only the hash pass may finish a first import"


async def test_sync_keeps_page_whose_file_lives_outside_the_source_dir(
    db_session, db_session_factory, mock_redis, layout
):
    """A merged gallery keeps pages whose files live in another folder (workbench_merge)."""
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)

        other = root / "other"
        other.mkdir()
        _write(other / "m01.jpg", b"merged")
        external = str(other / "m01.jpg")
        sha = hashlib.sha256(JPEG + b"merged").hexdigest()
        await db_session.execute(
            text(
                "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, external_path, ref_count) "
                "VALUES (:sha, :size, 'image', '.jpg', 'external', :path, 1)"
            ),
            {"sha": sha, "size": len(JPEG + b"merged"), "path": external},
        )
        await db_session.execute(
            text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
            {"sha": sha, "path": external},
        )
        await db_session.execute(
            text(
                "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path) "
                "VALUES (:gid, 2, 'm01.jpg', :sha, :path)"
            ),
            {"gid": gallery_id, "sha": sha, "path": external},
        )
        await db_session.commit()
        merged_before = [row for row in await _images(db_session, gallery_id) if row[2] == external]

        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    after = await _images(db_session, gallery_id)
    assert result.removed == 0
    assert result.pages == 2
    assert len(after) == 2
    assert [row for row in after if row[2] == external] == merged_before
