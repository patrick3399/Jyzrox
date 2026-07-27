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

    def hash_with_rename(path: Path):
        """Rename the source directory out from under the second file's hash."""
        from worker.source_identity import SourceFileIdentity

        payload = path.read_bytes()
        identity = SourceFileIdentity._from_stat(path, path.stat())
        if path.name == second.name:
            source.rename(renamed)
        return hashlib.sha256(payload).hexdigest(), identity

    symlink_spy = AsyncMock()
    emit_spy = AsyncMock()
    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.hash_file_with_identity", side_effect=hash_with_rename),
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
            text("SELECT (SELECT COUNT(*) FROM images WHERE gallery_id=:gid), (SELECT COUNT(*) FROM blob_locations)"),
            {"gid": gallery_id},
        )
    ).one()
    assert tuple(counts) == (0, 0)


# ---------------------------------------------------------------------------
# Per-file identity (SourceDirectoryIdentity cannot see an in-place swap)
# ---------------------------------------------------------------------------


def test_hash_and_identity_describe_the_same_bytes(tmp_path):
    from worker.source_identity import hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"payload")

    digest, identity = hash_file_with_identity(target)

    assert digest == hashlib.sha256(b"payload").hexdigest()
    stat = target.stat()
    assert (identity.device, identity.inode) == (stat.st_dev, stat.st_ino)
    assert identity.size == stat.st_size
    identity.assert_unchanged("noop")  # must not raise


def test_replacing_a_file_in_place_is_detected_though_the_directory_is_untouched(tmp_path):
    """The exact gap the directory-level check misses.

    Same directory, same filename → the directory's inode never changes, so
    every SourceDirectoryIdentity assertion passes while link mode would record
    a sha256 that no longer matches the bytes at the stored path.
    """
    from worker.source_identity import (
        SourceDirectoryIdentity,
        SourceFileChangedError,
        hash_file_with_identity,
    )

    target = tmp_path / "a.jpg"
    target.write_bytes(b"original")

    directory = SourceDirectoryIdentity.capture(tmp_path)
    _, identity = hash_file_with_identity(target)

    # Atomic replace: new inode behind the same name.
    replacement = tmp_path / "a.jpg.new"
    replacement.write_bytes(b"replaced content")
    replacement.replace(target)

    directory.assert_unchanged("after-swap")  # the old check is blind to this

    with pytest.raises(SourceFileChangedError, match="source file changed at commit"):
        identity.assert_unchanged("commit")


def test_rewriting_a_file_in_place_is_detected(tmp_path):
    """Same inode, new content — caught via size/mtime rather than inode."""
    import time

    from worker.source_identity import SourceFileChangedError, hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"original")
    _, identity = hash_file_with_identity(target)

    time.sleep(0.01)  # ensure mtime_ns actually moves
    with open(target, "r+b") as handle:
        handle.write(b"REWRITTEN-and-longer")

    with pytest.raises(SourceFileChangedError):
        identity.assert_unchanged("commit")


def test_deleted_file_is_reported_as_changed(tmp_path):
    from worker.source_identity import SourceFileChangedError, hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"payload")
    _, identity = hash_file_with_identity(target)
    target.unlink()

    with pytest.raises(SourceFileChangedError, match="unavailable"):
        identity.assert_unchanged("commit")


def test_hash_detects_a_file_growing_while_it_is_read(tmp_path, monkeypatch):
    """The read itself must not silently produce a digest for a moving target."""
    from worker import source_identity as mod

    target = tmp_path / "a.jpg"
    target.write_bytes(b"x" * 200)

    real_fstat = mod.os.fstat
    calls = {"n": 0}

    def _fstat(fd):
        calls["n"] += 1
        stat = real_fstat(fd)
        if calls["n"] == 1:
            return stat
        # Second fstat (after the read) reports a different size/mtime.
        fields = list(stat)
        fields[6] = stat.st_size + 10  # st_size
        return type(stat)(tuple(fields))

    monkeypatch.setattr(mod.os, "fstat", _fstat)

    with pytest.raises(mod.SourceFileChangedError, match="while being hashed"):
        mod.hash_file_with_identity(target)


async def test_link_import_aborts_when_a_file_is_swapped_after_hashing(
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    """End to end: the directory is untouched, so only the per-file check catches it.

    Without it the import committed rows whose blob_sha256 described the old
    bytes while Image.external_path pointed at a path now holding new ones.
    """
    from worker.importer import local_import_job
    from worker.source_identity import SourceFileIdentity

    source = tmp_path / "source-swap"
    source.mkdir()
    image = source / "001.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0original")
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', 'swap-after-hash', 'Swap', 'link', :path, 'importing')"
        ),
        {"path": str(source)},
    )
    await db_session.commit()
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id='swap-after-hash'"))
    ).scalar_one()

    def hash_then_swap(path: Path):
        payload = path.read_bytes()
        identity = SourceFileIdentity._from_stat(path, path.stat())
        # Atomic replace behind the same name — the parent dir is untouched.
        replacement = path.with_suffix(".new")
        replacement.write_bytes(b"\xff\xd8\xff\xe0replaced-and-longer")
        replacement.replace(path)
        return hashlib.sha256(payload).hexdigest(), identity

    symlink_spy = AsyncMock()
    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.hash_file_with_identity", side_effect=hash_then_swap),
        patch("worker.importer._validate_image_magic", return_value=True),
        patch("worker.importer.create_library_symlink", symlink_spy),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await local_import_job(
            {"redis": mock_redis},
            source_dir=str(source),
            mode="link",
            gallery_id=gallery_id,
        )

    assert result["status"] == "source_changed"
    counts = (
        await db_session.execute(
            text("SELECT (SELECT COUNT(*) FROM images WHERE gallery_id=:gid), (SELECT COUNT(*) FROM blobs)"),
            {"gid": gallery_id},
        )
    ).one()
    assert tuple(counts) == (0, 0), "no row may describe bytes that are no longer at that path"
