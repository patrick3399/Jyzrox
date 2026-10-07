"""Link imports commit in chunks and record stat fingerprints (ADR 0014)."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import text


async def _insert_link_gallery(db_session, source_id: str, source: Path) -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', :sid, 'T', 'link', :path, 'importing')"
        ),
        {"sid": source_id, "path": str(source)},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": source_id})
    ).scalar_one()


async def test_link_import_keeps_committed_chunk_when_source_changes_in_a_later_chunk(
    db_session, db_session_factory, mock_redis, tmp_path
):
    from services.source_identity import SourceFileIdentity
    from worker.importer import local_import_job

    source = tmp_path / "chunked"
    renamed = tmp_path / "chunked-renamed"
    source.mkdir()
    for index in range(1, 4):
        (source / f"{index:03d}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes([index]) * 8)
    gallery_id = await _insert_link_gallery(db_session, "chunked", source)

    def hash_then_rename_on_third(path: Path):
        payload = path.read_bytes()
        identity = SourceFileIdentity._from_stat(path, path.stat())
        if path.name == "003.jpg":
            source.rename(renamed)
        return hashlib.sha256(payload).hexdigest(), identity

    with (
        patch("worker.importer.LINK_IMPORT_CHUNK", 2, create=True),
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.hash_file_with_identity", side_effect=hash_then_rename_on_third),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer.create_library_symlink", new_callable=AsyncMock),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await local_import_job(
            {"redis": mock_redis}, source_dir=str(source), mode="link", gallery_id=gallery_id
        )

    assert result["status"] == "source_changed"
    row = (
        await db_session.execute(
            text(
                "SELECT pages, download_status, (SELECT COUNT(*) FROM images WHERE gallery_id=:gid) "
                "FROM galleries WHERE id=:gid"
            ),
            {"gid": gallery_id},
        )
    ).one()
    assert tuple(row) == (2, "partial", 2)


async def test_link_import_records_file_fingerprint_and_directory_mtime(
    db_session, db_session_factory, mock_redis, tmp_path
):
    from worker.importer import local_import_job

    source = tmp_path / "fingerprint"
    source.mkdir()
    image = source / "001.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fingerprint")
    gallery_id = await _insert_link_gallery(db_session, "fingerprint", source)

    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer.create_library_symlink", new_callable=AsyncMock),
        patch("worker.importer.write_gallery_sidecar", new_callable=AsyncMock),
        patch("core.queue.enqueue", new_callable=AsyncMock),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await local_import_job(
            {"redis": mock_redis}, source_dir=str(source), mode="link", gallery_id=gallery_id
        )

    assert result["status"] == "done"
    stat = image.stat()
    fingerprint = (
        await db_session.execute(
            text("SELECT source_size, source_mtime_ns FROM images WHERE gallery_id=:gid"), {"gid": gallery_id}
        )
    ).one()
    assert tuple(fingerprint) == (stat.st_size, stat.st_mtime_ns)
    dir_mtime = (
        await db_session.execute(text("SELECT source_dir_mtime_ns FROM galleries WHERE id=:gid"), {"gid": gallery_id})
    ).scalar_one()
    assert dir_mtime == source.stat().st_mtime_ns
