"""Regression coverage for link-import source identity (HR-012)."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text


def test_source_identity_accepts_content_changes_without_directory_replacement(tmp_path):
    from worker.source_identity import SourceDirectoryIdentity

    source = tmp_path / "source"
    source.mkdir()
    identity = SourceDirectoryIdentity.capture(source)
    (source / "new.jpg").write_bytes(b"new")

    identity.assert_unchanged("test")


def test_source_identity_rejects_rename_and_same_path_replacement(tmp_path):
    from worker.source_identity import SourceDirectoryChangedError, SourceDirectoryIdentity

    source = tmp_path / "source"
    source.mkdir()
    identity = SourceDirectoryIdentity.capture(source)
    source.rename(tmp_path / "renamed")

    with pytest.raises(SourceDirectoryChangedError, match="unavailable"):
        identity.assert_unchanged("renamed")

    source.mkdir()
    with pytest.raises(SourceDirectoryChangedError, match="expected"):
        identity.assert_unchanged("replaced")


async def test_link_import_rename_rolls_back_new_rows_and_reports_resumable(
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    from worker.importer import local_import_job

    source = tmp_path / "source"
    renamed = tmp_path / "renamed"
    source.mkdir()
    first = source / "001.jpg"
    second = source / "002.jpg"
    first.write_bytes(b"\xff\xd8\xff\xe0first")
    second.write_bytes(b"\xff\xd8\xff\xe0second")
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', 'rename-during-import', 'Rename', 'link', :path, 'importing')"
        ),
        {"path": str(source)},
    )
    await db_session.commit()
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id='rename-during-import'"))
    ).scalar_one()

    def hash_with_rename(path: Path) -> str:
        payload = path.read_bytes()
        if path.name == second.name:
            source.rename(renamed)
        return hashlib.sha256(payload).hexdigest()

    symlink_spy = AsyncMock()
    emit_spy = AsyncMock()
    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer._sha256", side_effect=hash_with_rename),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer.create_library_symlink", symlink_spy),
        patch("core.events.emit_safe", emit_spy),
    ):
        result = await local_import_job(
            {"redis": mock_redis},
            source_dir=str(source),
            mode="link",
            gallery_id=gallery_id,
        )

    assert result["status"] == "source_changed"
    assert result["processed"] == 0
    assert result["resumable"] is True
    assert renamed.is_dir()
    symlink_spy.assert_not_awaited()

    counts = (
        await db_session.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM images WHERE gallery_id=:gid), "
                "(SELECT COUNT(*) FROM blob_locations), "
                "(SELECT COUNT(*) FROM blobs)"
            ),
            {"gid": gallery_id},
        )
    ).one()
    assert tuple(counts) == (0, 0, 0)
    status = (
        await db_session.execute(text("SELECT download_status FROM galleries WHERE id=:gid"), {"gid": gallery_id})
    ).scalar_one()
    assert status == "failed"
    assert emit_spy.await_args is not None
    assert emit_spy.await_args.kwargs["reason"] == "source_changed"


async def test_link_import_rename_at_finalize_removes_deferred_symlink(
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    from services.cas import create_library_symlink as real_create_library_symlink
    from worker.importer import local_import_job

    source = tmp_path / "source-finalize"
    renamed = tmp_path / "renamed-finalize"
    library_root = tmp_path / "library"
    source.mkdir()
    image = source / "001.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0finalize")
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', 'rename-at-finalize', 'Rename', 'link', :path, 'importing')"
        ),
        {"path": str(source)},
    )
    await db_session.commit()
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id='rename-at-finalize'"))
    ).scalar_one()

    async def create_then_rename(*args, **kwargs):
        await real_create_library_symlink(*args, **kwargs)
        source.rename(renamed)

    cas_settings = MagicMock()
    cas_settings.data_library_path = str(library_root)
    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer.create_library_symlink", side_effect=create_then_rename),
        patch("services.cas.settings", cas_settings),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await local_import_job(
            {"redis": mock_redis},
            source_dir=str(source),
            mode="link",
            gallery_id=gallery_id,
        )

    assert result["status"] == "source_changed"
    link = library_root / "local" / "rename-at-finalize" / image.name
    assert not link.is_symlink()
    counts = (
        await db_session.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM images WHERE gallery_id=:gid), "
                "(SELECT COUNT(*) FROM blob_locations)"
            ),
            {"gid": gallery_id},
        )
    ).one()
    assert tuple(counts) == (0, 0)
