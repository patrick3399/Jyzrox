"""Link gallery sync against a real folder and the test DB (ADR 0014)."""

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


async def _gallery(db_session, source: Path, root: Path) -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, library_path, "
            "download_status) VALUES ('local', :sid, 'T', 'link', :path, :root, 'complete')"
        ),
        {"sid": source.name, "path": str(source), "root": str(root)},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": source.name})
    ).scalar_one()


async def _images(db_session, gallery_id: int) -> list[tuple]:
    rows = await db_session.execute(
        text(
            "SELECT id, filename, external_path, blob_sha256, page_num FROM images "
            "WHERE gallery_id=:gid ORDER BY page_num"
        ),
        {"gid": gallery_id},
    )
    return [tuple(row) for row in rows.all()]


@contextmanager
def _env(db_session_factory, library_root: Path):
    cas_settings = MagicMock()
    cas_settings.data_library_path = str(library_root)
    with (
        patch("services.link_sync.AsyncSessionLocal", db_session_factory),
        patch("services.cas.settings", cas_settings),
        patch("services.link_sync.emit_safe", new_callable=AsyncMock),
        patch("services.link_sync.write_gallery_sidecar", new_callable=AsyncMock),
        patch("services.link_sync.cleanup_unreferenced_thumbnails", new_callable=AsyncMock, return_value=set()),
        patch("core.queue.enqueue", new_callable=AsyncMock) as enqueue,
    ):
        yield enqueue


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "lib"
    source = root / "g1"
    source.mkdir(parents=True)
    return root, source, tmp_path / "library"


async def test_sync_unchanged_directory_mtime_skips_listing(db_session, db_session_factory, mock_redis, layout):
    from services import link_sync

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        first = await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)
        with patch("services.link_sync.scan_media_files", wraps=link_sync.scan_media_files) as scan:
            second = await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)

    assert (first.status, first.added, first.pages) == ("synced", 1, 1)
    assert second.status == "unchanged"
    scan.assert_not_called()


async def test_sync_adds_only_new_file_without_rehashing_existing(db_session, db_session_factory, mock_redis, layout):
    from services import link_sync

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library) as enqueue:
        await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)
        _write(source / "002.jpg", b"two")
        with patch("services.link_sync.hash_file_with_identity", wraps=link_sync.hash_file_with_identity) as hasher:
            result = await link_sync.sync_link_gallery(gallery_id, redis=mock_redis)

    assert (result.status, result.added, result.pages) == ("synced", 1, 2)
    assert [call.args[0].name for call in hasher.call_args_list] == ["002.jpg"]
    assert [row[1] for row in await _images(db_session, gallery_id)] == ["001.jpg", "002.jpg"]
    assert (library / "local" / "g1" / "002.jpg").is_symlink()
    assert "thumbnail_job" in [call.args[0] for call in enqueue.await_args_list]


async def test_sync_renamed_file_keeps_image_id(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        before = await _images(db_session, gallery_id)
        (source / "001.jpg").rename(source / "cover.jpg")
        result = await sync_link_gallery(gallery_id, redis=mock_redis)

    after = await _images(db_session, gallery_id)
    assert (result.renamed, result.added, result.removed) == (1, 0, 0)
    assert len(after) == 1
    assert after[0][0] == before[0][0], "a rename must not replace the Image row"
    assert after[0][1:3] == ("cover.jpg", str(source / "cover.jpg"))
    assert (library / "local" / "g1" / "cover.jpg").is_symlink()
    assert not (library / "local" / "g1" / "001.jpg").is_symlink()


async def test_sync_overwritten_file_repoints_same_image_row(db_session, db_session_factory, mock_redis, layout):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"original")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        before = await _images(db_session, gallery_id)
        _write(source / "001.jpg", b"edited-and-longer", age_s=30)
        result = await sync_link_gallery(gallery_id, redis=mock_redis, force=True)

    after = await _images(db_session, gallery_id)
    assert result.replaced == 1
    assert len(after) == 1, "an in-place overwrite must not add a second page"
    assert after[0][0] == before[0][0]
    assert after[0][3] == hashlib.sha256(JPEG + b"edited-and-longer").hexdigest()


async def test_sync_deleted_file_removes_row_symlink_and_reference(db_session, db_session_factory, mock_redis, layout):
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
    ref_count = (
        await db_session.execute(
            text("SELECT ref_count FROM blobs WHERE sha256=:sha"),
            {"sha": hashlib.sha256(JPEG + b"two").hexdigest()},
        )
    ).scalar_one()
    assert ref_count == 0


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


async def test_sync_over_inline_limit_returns_deferred_without_changes(
    db_session, db_session_factory, mock_redis, layout
):
    from services.link_sync import sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _env(db_session_factory, library):
        result = await sync_link_gallery(gallery_id, redis=mock_redis, max_hash_files=0)

    assert (result.status, result.pending) == ("deferred", 1)
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
