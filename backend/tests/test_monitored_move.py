"""Regression coverage for monitored local-gallery moves (HR-013)."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text


@pytest.mark.parametrize("cross_root", [False, True], ids=["same-root", "cross-root"])
async def test_monitored_directory_move_preserves_gallery_and_user_state(
    cross_root,
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    from worker.scan import move_library_path_job, reconcile_library_path_job

    root_a = tmp_path / "source-a"
    root_b = tmp_path / "source-b"
    library_root = tmp_path / "library"
    root_a.mkdir()
    root_b.mkdir()
    old_dir = root_a / "old-gallery"
    old_dir.mkdir()
    old_image = old_dir / "001.jpg"
    old_image.write_bytes(b"monitored-move")

    await db_session.execute(
        text("INSERT INTO users (username, password_hash, role) VALUES ('move-user', 'hash', 'admin')")
    )
    user_id = (await db_session.execute(text("SELECT id FROM users WHERE username='move-user'"))).scalar_one()
    for root in (root_a, root_b):
        await db_session.execute(
            text(
                "INSERT INTO library_paths (path, label, pattern, import_mode, enabled, monitor) "
                "VALUES (:path, :label, '{title}', 'link', 1, 1)"
            ),
            {"path": str(root), "label": root.name},
        )
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(source, source_id, title, uploader, rating, favorited, pages, import_mode, "
            "library_path, source_path, download_status) "
            "VALUES ('local', 'old-gallery', 'User title', 'User uploader', 4, 1, 1, 'link', "
            ":library_path, :source_path, 'complete')"
        ),
        {"library_path": str(root_a), "source_path": str(old_dir)},
    )
    gallery_id = (await db_session.execute(text("SELECT id FROM galleries WHERE source_id='old-gallery'"))).scalar_one()
    blob_sha256 = hashlib.sha256(old_image.read_bytes()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, external_path, ref_count) "
            "VALUES (:sha, :size, '.jpg', 'external', :path, 1)"
        ),
        {"sha": blob_sha256, "size": old_image.stat().st_size, "path": str(old_image)},
    )
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
        {"sha": blob_sha256, "path": str(old_image)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path) "
            "VALUES (:gallery_id, 1, '001.jpg', :sha, :path)"
        ),
        {"gallery_id": gallery_id, "sha": blob_sha256, "path": str(old_image)},
    )
    image_id = (
        await db_session.execute(text("SELECT id FROM images WHERE gallery_id=:gallery_id"), {"gallery_id": gallery_id})
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (:user_id, :gallery_id)"),
        {"user_id": user_id, "gallery_id": gallery_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO read_progress (user_id, gallery_id, last_page, last_image_id) "
            "VALUES (:user_id, :gallery_id, 1, :image_id)"
        ),
        {"user_id": user_id, "gallery_id": gallery_id, "image_id": image_id},
    )
    await db_session.execute(
        text("INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (:gallery_id, :sha)"),
        {"gallery_id": gallery_id, "sha": blob_sha256},
    )
    await db_session.execute(
        text("INSERT INTO collections (user_id, name, cover_gallery_id) VALUES (:user_id, 'Kept', :gallery_id)"),
        {"user_id": user_id, "gallery_id": gallery_id},
    )
    collection_id = (await db_session.execute(text("SELECT id FROM collections WHERE name='Kept'"))).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO collection_galleries (collection_id, gallery_id, position) "
            "VALUES (:collection_id, :gallery_id, 7)"
        ),
        {"collection_id": collection_id, "gallery_id": gallery_id},
    )
    await db_session.commit()

    old_library_dir = library_root / "local" / "old-gallery"
    old_library_dir.mkdir(parents=True)
    (old_library_dir / ".gallery-owner").write_text("local:old-gallery", encoding="utf-8")
    (old_library_dir / "001.jpg").symlink_to(old_image)

    destination_root = root_b if cross_root else root_a
    new_dir = destination_root / "renamed-gallery"
    old_dir.rename(new_dir)
    new_image = new_dir / "001.jpg"
    destination_stat = new_dir.stat()
    mock_redis.get = AsyncMock(return_value=b"1")
    scan_settings = MagicMock(library_monitor_enabled=True, data_library_path=str(library_root))
    cas_settings = MagicMock(data_library_path=str(library_root))

    with (
        patch("worker.scan.AsyncSessionLocal", db_session_factory),
        patch("worker.scan.get_monitored_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.settings", scan_settings),
        patch("services.cas.settings", cas_settings),
        patch("core.events.emit_safe", new_callable=AsyncMock) as emit_spy,
    ):
        if cross_root:
            result = await reconcile_library_path_job(
                {"redis": mock_redis},
                old_paths=[str(old_dir)],
                new_path=str(new_dir),
                destination_device=destination_stat.st_dev,
                destination_inode=destination_stat.st_ino,
                watcher_origin=True,
            )
        else:
            result = await move_library_path_job(
                {"redis": mock_redis},
                old_path=str(old_dir),
                new_path=str(new_dir),
                destination_device=destination_stat.st_dev,
                destination_inode=destination_stat.st_ino,
                watcher_origin=True,
            )

    assert result == {
        "status": "moved",
        "gallery_id": gallery_id,
        "old_source_id": "old-gallery",
        "source_id": "renamed-gallery",
        "old_path": str(old_dir),
        "new_path": str(new_dir),
    }
    gallery = (
        await db_session.execute(
            text(
                "SELECT id, source_id, source_path, library_path, title, uploader, rating, favorited "
                "FROM galleries WHERE id=:gallery_id"
            ),
            {"gallery_id": gallery_id},
        )
    ).one()
    assert tuple(gallery) == (
        gallery_id,
        "renamed-gallery",
        str(new_dir),
        str(destination_root),
        "User title",
        "User uploader",
        4,
        1,
    )
    image_path = (
        await db_session.execute(text("SELECT external_path FROM images WHERE id=:image_id"), {"image_id": image_id})
    ).scalar_one()
    assert image_path == str(new_image)
    state_counts = (
        await db_session.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM user_favorites WHERE gallery_id=:gallery_id), "
                "(SELECT COUNT(*) FROM read_progress WHERE gallery_id=:gallery_id AND last_page=1), "
                "(SELECT COUNT(*) FROM excluded_blobs WHERE gallery_id=:gallery_id), "
                "(SELECT COUNT(*) FROM collection_galleries WHERE gallery_id=:gallery_id AND position=7), "
                "(SELECT COUNT(*) FROM blob_locations WHERE blob_sha256=:sha AND external_path=:new_path)"
            ),
            {"gallery_id": gallery_id, "sha": blob_sha256, "new_path": str(new_image)},
        )
    ).one()
    assert tuple(state_counts) == (1, 1, 1, 1, 1)

    new_library_dir = library_root / "local" / "renamed-gallery"
    assert not old_library_dir.exists()
    assert (new_library_dir / ".gallery-owner").read_text(encoding="utf-8") == "local:renamed-gallery"
    assert (new_library_dir / "001.jpg").resolve() == new_image
    emit_call = emit_spy.await_args
    assert emit_call is not None
    assert emit_call.kwargs["resource_id"] == gallery_id
