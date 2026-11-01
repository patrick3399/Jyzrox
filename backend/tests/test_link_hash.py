"""Background hash pass for pending link pages (ADR 0015)."""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text

from tests.test_link_sync import _gallery, _images, _write, layout  # noqa: F401


@contextmanager
def _hash_env(db_session_factory, library_root: Path):
    """Like test_link_sync._env, but the real hasher runs."""
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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _ref_count(db_session, sha: str) -> int | None:
    return (
        await db_session.execute(text("SELECT ref_count FROM blobs WHERE sha256=:sha"), {"sha": sha})
    ).scalar_one_or_none()


async def _gallery_row(db_session, gallery_id: int) -> tuple:
    row = await db_session.execute(
        text("SELECT download_status, pages FROM galleries WHERE id=:gid"), {"gid": gallery_id}
    )
    return tuple(row.one())


async def test_hash_attaches_blob_and_counts_one_reference_per_page(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services.link_sync import LinkHashResult, hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"two")
    gallery_id = await _gallery(db_session, source, root)

    with _hash_env(db_session_factory, library) as enqueue:
        await sync_link_gallery(gallery_id, redis=mock_redis)
        result = await hash_pending_images(gallery_id)

    assert result == LinkHashResult(status="done", hashed=2, failed=0, remaining=0, pages=2)
    rows = await _images(db_session, gallery_id)
    assert [row[3] for row in rows] == [_sha(source / "001.jpg"), _sha(source / "002.jpg")]
    for sha in (row[3] for row in rows):
        assert await _ref_count(db_session, sha) == 1
    locations = (await db_session.execute(text("SELECT blob_sha256, external_path FROM blob_locations"))).all()
    assert sorted(tuple(row) for row in locations) == sorted((row[3], row[2]) for row in rows)
    queued = [call.args[0] for call in enqueue.await_args_list]
    assert "thumbnail_job" in queued
    assert "cover_thumbnail_job" in queued


async def test_hash_same_content_files_stay_separate_pages(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"same")
    _write(source / "002.jpg", b"same")
    gallery_id = await _gallery(db_session, source, root)

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        result = await hash_pending_images(gallery_id)

    rows = await _images(db_session, gallery_id)
    assert result.hashed == 2
    assert len(rows) == 2
    assert rows[0][3] == rows[1][3] == _sha(source / "001.jpg")
    assert await _ref_count(db_session, rows[0][3]) == 2


async def test_hash_file_changed_since_registration_stays_pending(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"original")
    gallery_id = await _gallery(db_session, source, root)

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        _write(source / "001.jpg", b"rewritten-and-longer", age_s=30)
        result = await hash_pending_images(gallery_id)

    assert (result.hashed, result.failed, result.remaining) == (0, 1, 1)
    rows = await _images(db_session, gallery_id)
    assert rows[0][3] is None
    assert await _ref_count(db_session, _sha(source / "001.jpg")) is None


async def test_hash_row_deleted_during_pass_takes_no_reference(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services import link_sync
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)
    real_hash_path = link_sync._hash_path

    async def hash_then_delete_row(path: str):
        outcome = await real_hash_path(path)
        async with db_session_factory() as other:
            await other.execute(text("DELETE FROM images WHERE gallery_id=:gid"), {"gid": gallery_id})
            await other.commit()
        return outcome

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        with patch("services.link_sync._hash_path", hash_then_delete_row):
            result = await hash_pending_images(gallery_id)

    assert result.hashed == 0
    assert await _ref_count(db_session, _sha(source / "001.jpg")) == 0, "no reference without an updated row"


async def test_hash_excluded_content_becomes_excluded_visibility(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"keep")
    _write(source / "002.jpg", b"hidden")
    gallery_id = await _gallery(db_session, source, root)
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:gid, :sha)"),
        {"gid": gallery_id, "sha": _sha(source / "002.jpg")},
    )
    await db_session.commit()

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        result = await hash_pending_images(gallery_id)

    rows = (
        await db_session.execute(
            text("SELECT filename, visibility FROM images WHERE gallery_id=:gid ORDER BY page_num"),
            {"gid": gallery_id},
        )
    ).all()
    assert [tuple(row) for row in rows] == [("001.jpg", "active"), ("002.jpg", "excluded")]
    assert (result.hashed, result.remaining, result.pages) == (2, 0, 1)
    assert (await _gallery_row(db_session, gallery_id))[1] == 1


async def test_hash_first_import_reaches_complete_only_when_nothing_is_pending(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"two")
    clean_id = await _gallery(db_session, source, root, status="importing")

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(clean_id, redis=mock_redis)
        clean = await hash_pending_images(clean_id)
    assert clean.remaining == 0
    assert await _gallery_row(db_session, clean_id) == ("complete", 2)

    other = root / "g2"
    other.mkdir()
    _write(other / "001.jpg", b"three")
    _write(other / "002.jpg", b"four")
    partial_id = await _gallery(db_session, other, root, status="importing")
    with _hash_env(db_session_factory, library):
        await sync_link_gallery(partial_id, redis=mock_redis)
        _write(other / "002.jpg", b"four-but-rewritten", age_s=30)
        partial = await hash_pending_images(partial_id)
    assert (partial.hashed, partial.failed, partial.remaining) == (1, 1, 1)
    assert await _gallery_row(db_session, partial_id) == ("partial", 2)


async def test_hash_trashed_gallery_is_not_mutated(db_session, db_session_factory, mock_redis, layout):  # noqa: F811
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        await db_session.execute(
            text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id=:gid"), {"gid": gallery_id}
        )
        await db_session.commit()
        result = await hash_pending_images(gallery_id)

    assert result.status == "skipped_trashed"
    assert [row[3] for row in await _images(db_session, gallery_id)] == [None]
    assert (await db_session.execute(text("SELECT COUNT(*) FROM blobs"))).scalar_one() == 0


async def test_hash_is_replayable(db_session, db_session_factory, mock_redis, layout):  # noqa: F811
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        first = await hash_pending_images(gallery_id)
        second = await hash_pending_images(gallery_id)

    assert (first.hashed, second.hashed) == (2, 0)
    assert second.remaining == 0
    assert await _ref_count(db_session, _sha(source / "001.jpg")) == 2


async def test_hash_page_whose_fingerprint_moved_during_pass_takes_no_reference(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    """A sync that re-fingerprints the row mid-pass must win over the stale hash."""
    from services import link_sync
    from services.link_sync import hash_pending_images, sync_link_gallery

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root)
    real_hash_path = link_sync._hash_path

    async def hash_then_refingerprint(path: str):
        outcome = await real_hash_path(path)
        async with db_session_factory() as other:
            await other.execute(
                text("UPDATE images SET source_mtime_ns = source_mtime_ns + 1 WHERE gallery_id=:gid"),
                {"gid": gallery_id},
            )
            await other.commit()
        return outcome

    with _hash_env(db_session_factory, library):
        await sync_link_gallery(gallery_id, redis=mock_redis)
        with patch("services.link_sync._hash_path", hash_then_refingerprint):
            result = await hash_pending_images(gallery_id)

    assert result.hashed == 0
    assert [row[3] for row in await _images(db_session, gallery_id)] == [None]
    assert await _ref_count(db_session, _sha(source / "001.jpg")) == 0
