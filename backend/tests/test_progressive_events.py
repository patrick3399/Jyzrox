"""ProgressiveImporter: library events on rollback, include_excluded restore, and the keep path (finalize_kept)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select, text

from core.events import EventType
from db.models import ExcludedBlob, Image
from tests.test_progressive import _insert_blob, _insert_gallery, _insert_image, _make_session_factory_cm

SHA = "ab" * 32


def _fs_patches(db_session_factory):
    return (
        patch("worker.progressive.AsyncSessionLocal", _make_session_factory_cm(db_session_factory)),
        patch("worker.progressive.library_dir", return_value=Path("/nonexistent/lib")),
        patch("worker.progressive.thumb_dir", return_value=Path("/nonexistent/thumb")),
    )


async def test_cancel_cleanup_of_new_gallery_emits_gallery_deleted(db_session, db_session_factory):
    """Task 0 regression: cancel hard-deletes the row, so the library grid needs gallery.deleted."""
    from worker.progressive import ProgressiveImporter

    gallery_id = await _insert_gallery(db_session, source_id="evt_001")
    await _insert_blob(db_session, SHA, ref_count=1)
    await _insert_image(db_session, gallery_id, 1, SHA)
    importer = ProgressiveImporter(db_job_id=None, user_id=None)
    importer.gallery_id, importer.source, importer.source_id = gallery_id, "test_source", "evt_001"

    emit = AsyncMock()
    p1, p2, p3 = _fs_patches(db_session_factory)
    with p1, p2, p3, patch("worker.progressive.emit_safe", emit):
        await importer.cleanup()

    emit.assert_any_await(EventType.GALLERY_DELETED, resource_type="gallery", resource_id=gallery_id)
    assert all(c.args[0] != EventType.GALLERY_UPDATED for c in emit.await_args_list)
    row = (await db_session.execute(text("SELECT id FROM galleries WHERE id = :i"), {"i": gallery_id})).fetchone()
    assert row is None


async def test_abort_keeping_gallery_emits_gallery_updated(db_session, db_session_factory):
    from worker.progressive import ProgressiveImporter

    gallery_id = await _insert_gallery(db_session, source_id="evt_002")
    await _insert_blob(db_session, SHA, ref_count=1)
    await _insert_image(db_session, gallery_id, 1, SHA)
    importer = ProgressiveImporter(db_job_id=None, user_id=None)
    importer.gallery_id, importer.source, importer.source_id = gallery_id, "test_source", "evt_002"

    emit = AsyncMock()
    p1, p2, p3 = _fs_patches(db_session_factory)
    with p1, p2, p3, patch("worker.progressive.emit_safe", emit):
        await importer.abort()

    emit.assert_any_await(EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=gallery_id)


async def _import_excluded_file(db_session, db_session_factory, tmp_path, *, include_excluded):
    from worker.progressive import ProgressiveImporter

    gallery_id = await _insert_gallery(db_session, source_id="exc_001")
    await _insert_blob(db_session, SHA, ref_count=0)
    db_session.add(ExcludedBlob(gallery_id=gallery_id, blob_sha256=SHA))
    await db_session.commit()
    path = tmp_path / "001.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)

    importer = ProgressiveImporter(db_job_id=None, user_id=None, include_excluded=include_excluded)
    importer.gallery_id, importer.source, importer.source_id = gallery_id, "test_source", "exc_001"
    with (
        patch("worker.progressive.AsyncSessionLocal", _make_session_factory_cm(db_session_factory)),
        patch("worker.progressive.store_blob", AsyncMock(return_value=MagicMock())),
        patch("worker.progressive.increment_ref_count", AsyncMock()),
        patch("worker.progressive.create_library_symlink", AsyncMock()),
        patch("worker.progressive._validate_image_magic", return_value=True),
        patch("worker.progressive.emit_safe", AsyncMock()),
    ):
        await importer._load_gallery_state()
        await importer.import_file(path, sha256=SHA)
        await importer._drain_tasks()
    return importer, gallery_id


async def test_include_excluded_import_removes_excluded_blob_row(db_session, db_session_factory, tmp_path):
    importer, gallery_id = await _import_excluded_file(db_session, db_session_factory, tmp_path, include_excluded=True)

    assert importer.import_success_count == 1
    assert importer.skipped_excluded_count == 0
    db_session.expire_all()
    assert (await db_session.execute(select(ExcludedBlob).where(ExcludedBlob.gallery_id == gallery_id))).first() is None
    assert (await db_session.execute(select(Image).where(Image.gallery_id == gallery_id))).scalars().all()


async def test_excluded_blob_stays_out_without_include_excluded(db_session, db_session_factory, tmp_path):
    """Default behaviour is unchanged: a purged image is skipped and its exclusion kept."""
    importer, gallery_id = await _import_excluded_file(db_session, db_session_factory, tmp_path, include_excluded=False)

    assert importer.import_success_count == 0
    assert importer.skipped_excluded_count == 1
    db_session.expire_all()
    assert (await db_session.execute(select(ExcludedBlob).where(ExcludedBlob.gallery_id == gallery_id))).first()
    assert not (await db_session.execute(select(Image).where(Image.gallery_id == gallery_id))).scalars().all()


async def test_has_processed_is_true_only_for_paths_handed_to_import_file(tmp_path):
    from worker.progressive import ProgressiveImporter

    importer = ProgressiveImporter(db_job_id=None, user_id=None)
    seen, other = tmp_path / "1.jpg", tmp_path / "2.jpg"
    await importer.import_file(seen)  # not on disk: recorded, then skipped by _import_single
    await importer._drain_tasks()

    assert importer.has_processed(seen) is True
    assert importer.has_processed(other) is False


async def _kept_importer(db_session, tmp_path, *, success: int, status="downloading"):
    from worker.progressive import ProgressiveImporter

    gallery_id = await _insert_gallery(db_session, source_id="keep_001", download_status=status)
    await _insert_blob(db_session, SHA)
    for page in range(1, success + 1):
        await _insert_image(db_session, gallery_id, page, SHA)
    importer = ProgressiveImporter(db_job_id=None, user_id=None)
    importer.gallery_id, importer.source, importer.source_id = gallery_id, "test_source", "keep_001"
    importer._import_success_count = success
    dest = tmp_path / "dest"
    dest.mkdir()
    return importer, gallery_id, dest


async def _status(db_session, gallery_id):
    db_session.expire_all()
    return (
        await db_session.execute(text("SELECT download_status FROM galleries WHERE id=:i"), {"i": gallery_id})
    ).scalar()


async def test_finalize_kept_subscription_stop_marks_gallery_complete(db_session, db_session_factory, tmp_path):
    importer, gallery_id, dest = await _kept_importer(db_session, tmp_path, success=3)
    with patch("worker.progressive.AsyncSessionLocal", _make_session_factory_cm(db_session_factory)):
        result = await importer.finalize_kept(dest, mode="subscription_incremental")

    assert result == gallery_id
    assert await _status(db_session, gallery_id) == "complete"


async def test_finalize_kept_download_stop_keeps_gallery_partial_and_resumable(
    db_session, db_session_factory, tmp_path
):
    importer, gallery_id, dest = await _kept_importer(db_session, tmp_path, success=3)
    with patch("worker.progressive.AsyncSessionLocal", _make_session_factory_cm(db_session_factory)):
        await importer.finalize_kept(dest, mode="download")

    assert await _status(db_session, gallery_id) == "partial"


async def test_finalize_kept_new_gallery_with_nothing_imported_is_rolled_back_not_kept_empty(
    db_session, db_session_factory, tmp_path
):
    importer, gallery_id, dest = await _kept_importer(db_session, tmp_path, success=0)
    p1, p2, p3 = _fs_patches(db_session_factory)
    with p1, p2, p3, patch("worker.progressive.emit_safe", AsyncMock()):
        result = await importer.finalize_kept(dest, mode="subscription_initial")

    assert result is None
    row = (await db_session.execute(text("SELECT id FROM galleries WHERE id = :i"), {"i": gallery_id})).fetchone()
    assert row is None
