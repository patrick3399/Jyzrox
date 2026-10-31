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


async def test_reconcile_skips_hashing_when_no_candidate_matches_names_and_sizes(
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    """The watcher pairs a create with every recent delete, so most candidates
    are unrelated. Ruling those out must not cost a full-directory sha256 —
    a bulk reorganisation would otherwise re-hash each moved gallery once per
    candidate directory."""
    from worker.scan import reconcile_library_path_job

    root = tmp_path / "lib"
    root.mkdir()
    old_dir = root / "unrelated-gallery"
    old_dir.mkdir()
    (old_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0aaaa")

    # A gallery whose recorded contents cannot match the destination.
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', 'unrelated-gallery', 'Unrelated', 'link', :path, 'complete')"
        ),
        {"path": str(old_dir)},
    )
    await db_session.commit()
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id='unrelated-gallery'"))
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO blobs (sha256, file_size, extension, ref_count) VALUES (:sha, 5, '.jpg', 1)"),
        {"sha": "aa" * 32},
    )
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, 1, '001.jpg', :sha)"),
        {"gid": gallery_id, "sha": "aa" * 32},
    )
    await db_session.commit()

    # Destination has the same filename but a different size → cannot be a match.
    new_dir = root / "brand-new-gallery"
    new_dir.mkdir()
    (new_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"z" * 500)
    destination_stat = new_dir.stat()

    mock_redis.get = AsyncMock(return_value=b"1")
    sha_spy = MagicMock(side_effect=AssertionError("must not hash: sizes already rule this out"))

    with (
        patch("worker.scan.AsyncSessionLocal", db_session_factory),
        patch("worker.scan.get_monitored_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.settings", MagicMock(library_monitor_enabled=True, data_library_path=str(tmp_path))),
        patch("worker.scan._sha256", sha_spy),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await reconcile_library_path_job(
            {"redis": mock_redis},
            old_paths=[str(old_dir)],
            new_path=str(new_dir),
            destination_device=destination_stat.st_dev,
            destination_inode=destination_stat.st_ino,
            watcher_origin=True,
        )

    assert result["status"] == "conflict"
    assert result["reason"] == "content_mismatch"
    sha_spy.assert_not_called()


async def test_reconcile_still_hashes_a_size_compatible_candidate(
    db_session,
    db_session_factory,
    mock_redis,
    tmp_path,
):
    """The prefilter must not become the decision: identical sizes still go to
    the exact content signature."""
    from worker.scan import reconcile_library_path_job

    root = tmp_path / "lib"
    root.mkdir()
    old_dir = root / "same-size-gallery"
    old_dir.mkdir()
    payload = b"\xff\xd8\xff\xe0aaaa"

    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status) "
            "VALUES ('local', 'same-size-gallery', 'SameSize', 'link', :path, 'complete')"
        ),
        {"path": str(old_dir)},
    )
    await db_session.commit()
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id='same-size-gallery'"))
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO blobs (sha256, file_size, extension, ref_count) VALUES (:sha, :size, '.jpg', 1)"),
        {"sha": "bb" * 32, "size": len(payload)},
    )
    await db_session.execute(
        text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:gid, 1, '001.jpg', :sha)"),
        {"gid": gallery_id, "sha": "bb" * 32},
    )
    await db_session.commit()

    new_dir = root / "moved-here"
    new_dir.mkdir()
    (new_dir / "001.jpg").write_bytes(payload)  # same size, different content
    destination_stat = new_dir.stat()

    mock_redis.get = AsyncMock(return_value=b"1")
    sha_spy = MagicMock(return_value="cc" * 32)  # not the recorded sha

    with (
        patch("worker.scan.AsyncSessionLocal", db_session_factory),
        patch("worker.scan.get_monitored_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.settings", MagicMock(library_monitor_enabled=True, data_library_path=str(tmp_path))),
        patch("worker.scan._sha256", sha_spy),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await reconcile_library_path_job(
            {"redis": mock_redis},
            old_paths=[str(old_dir)],
            new_path=str(new_dir),
            destination_device=destination_stat.st_dev,
            destination_inode=destination_stat.st_ino,
            watcher_origin=True,
        )

    sha_spy.assert_called_once()
    assert result["status"] == "conflict"
    assert result["reason"] == "content_mismatch"


async def _seed_gallery_with_pending_pages(db_session, root_a, root_b, old_dir, library_root):
    """A link gallery with one hashed page (001.jpg) and one pending page (002.jpg)."""
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
            "INSERT INTO galleries (source, source_id, title, pages, import_mode, library_path, source_path, "
            "download_status) VALUES ('local', 'old-gallery', 'Mixed', 2, 'link', :library_path, :source_path, "
            "'importing')"
        ),
        {"library_path": str(root_a), "source_path": str(old_dir)},
    )
    gallery_id = (await db_session.execute(text("SELECT id FROM galleries WHERE source_id='old-gallery'"))).scalar_one()
    hashed_file = old_dir / "001.jpg"
    pending_file = old_dir / "002.jpg"
    sha = hashlib.sha256(hashed_file.read_bytes()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, external_path, ref_count) "
            "VALUES (:sha, :size, '.jpg', 'external', :path, 1)"
        ),
        {"sha": sha, "size": hashed_file.stat().st_size, "path": str(hashed_file)},
    )
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
        {"sha": sha, "path": str(hashed_file)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path, source_size) VALUES "
            "(:gid, 1, '001.jpg', :sha, :hashed, :hashed_size), "
            "(:gid, 2, '002.jpg', NULL, :pending, :pending_size)"
        ),
        {
            "gid": gallery_id,
            "sha": sha,
            "hashed": str(hashed_file),
            "hashed_size": hashed_file.stat().st_size,
            "pending": str(pending_file),
            "pending_size": pending_file.stat().st_size,
        },
    )
    await db_session.commit()
    old_library_dir = library_root / "local" / "old-gallery"
    old_library_dir.mkdir(parents=True)
    (old_library_dir / ".gallery-owner").write_text("local:old-gallery", encoding="utf-8")
    (old_library_dir / "001.jpg").symlink_to(hashed_file)
    (old_library_dir / "002.jpg").symlink_to(pending_file)
    return gallery_id, sha


def _move_patches(db_session_factory, library_root, sha_spy=None):
    scan_settings = MagicMock(library_monitor_enabled=True, data_library_path=str(library_root))
    patches = [
        patch("worker.scan.AsyncSessionLocal", db_session_factory),
        patch("worker.scan.get_monitored_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.settings", scan_settings),
        patch("services.cas.settings", MagicMock(data_library_path=str(library_root))),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ]
    if sha_spy is not None:
        patches.append(patch("worker.scan._sha256", sha_spy))
    return patches


async def test_monitored_move_keeps_gallery_identity_with_pending_pages(
    db_session, db_session_factory, mock_redis, tmp_path
):
    """A pending page has no hash to compare after the move: it is verified by
    size, gets no BlobLocation, and its link follows the moved file."""
    from contextlib import ExitStack

    from worker.scan import _sha256, move_library_path_job

    root_a, root_b, library_root = tmp_path / "source-a", tmp_path / "source-b", tmp_path / "library"
    root_a.mkdir()
    root_b.mkdir()
    old_dir = root_a / "old-gallery"
    old_dir.mkdir()
    (old_dir / "001.jpg").write_bytes(b"hashed-page")
    (old_dir / "002.jpg").write_bytes(b"pending-page-bytes")
    gallery_id, sha = await _seed_gallery_with_pending_pages(db_session, root_a, root_b, old_dir, library_root)

    new_dir = root_a / "renamed-gallery"
    old_dir.rename(new_dir)
    destination_stat = new_dir.stat()
    mock_redis.get = AsyncMock(return_value=b"1")
    hashed_paths: list[str] = []

    def spy(path):
        hashed_paths.append(path.name)
        return _sha256(path)

    with ExitStack() as stack:
        for p in _move_patches(db_session_factory, library_root, MagicMock(side_effect=spy)):
            stack.enter_context(p)
        result = await move_library_path_job(
            {"redis": mock_redis},
            old_path=str(old_dir),
            new_path=str(new_dir),
            destination_device=destination_stat.st_dev,
            destination_inode=destination_stat.st_ino,
            watcher_origin=True,
        )

    assert result["status"] == "moved", result
    assert result["gallery_id"] == gallery_id
    assert hashed_paths == ["001.jpg"], "a pending page must not be hashed by the move"
    paths = dict(
        (
            await db_session.execute(
                text("SELECT filename, external_path FROM images WHERE gallery_id=:g"), {"g": gallery_id}
            )
        )
        .tuples()
        .all()
    )
    assert paths == {"001.jpg": str(new_dir / "001.jpg"), "002.jpg": str(new_dir / "002.jpg")}
    locations = (await db_session.execute(text("SELECT external_path FROM blob_locations"))).scalars().all()
    assert sorted(locations) == sorted([str(old_dir / "001.jpg"), str(new_dir / "001.jpg")])
    new_library_dir = library_root / "local" / "renamed-gallery"
    assert (new_library_dir / "002.jpg").resolve() == new_dir / "002.jpg"


async def test_monitored_move_refuses_a_pending_page_whose_size_changed(
    db_session, db_session_factory, mock_redis, tmp_path
):
    from contextlib import ExitStack

    from worker.scan import move_library_path_job

    root_a, root_b, library_root = tmp_path / "source-a", tmp_path / "source-b", tmp_path / "library"
    root_a.mkdir()
    root_b.mkdir()
    old_dir = root_a / "old-gallery"
    old_dir.mkdir()
    (old_dir / "001.jpg").write_bytes(b"hashed-page")
    (old_dir / "002.jpg").write_bytes(b"pending-page-bytes")
    await _seed_gallery_with_pending_pages(db_session, root_a, root_b, old_dir, library_root)

    new_dir = root_a / "renamed-gallery"
    old_dir.rename(new_dir)
    (new_dir / "002.jpg").write_bytes(b"different size entirely!!")
    destination_stat = new_dir.stat()
    mock_redis.get = AsyncMock(return_value=b"1")

    with ExitStack() as stack:
        for p in _move_patches(db_session_factory, library_root):
            stack.enter_context(p)
        result = await move_library_path_job(
            {"redis": mock_redis},
            old_path=str(old_dir),
            new_path=str(new_dir),
            destination_device=destination_stat.st_dev,
            destination_inode=destination_stat.st_ino,
            watcher_origin=True,
        )

    assert result["status"] == "conflict"
    assert "size does not match" in result["error"]


async def test_cross_root_move_matches_gallery_with_pending_pages(db_session, db_session_factory, mock_redis, tmp_path):
    """The size signature counts a pending page by (filename, source_size) and
    the hash signature leaves it out on both sides."""
    from contextlib import ExitStack

    from worker.scan import _sha256, reconcile_library_path_job

    root_a, root_b, library_root = tmp_path / "source-a", tmp_path / "source-b", tmp_path / "library"
    root_a.mkdir()
    root_b.mkdir()
    old_dir = root_a / "old-gallery"
    old_dir.mkdir()
    (old_dir / "001.jpg").write_bytes(b"hashed-page")
    (old_dir / "002.jpg").write_bytes(b"pending-page-bytes")
    gallery_id, _ = await _seed_gallery_with_pending_pages(db_session, root_a, root_b, old_dir, library_root)

    new_dir = root_b / "renamed-gallery"
    new_dir.mkdir()
    (new_dir / "001.jpg").write_bytes(b"hashed-page")
    (new_dir / "002.jpg").write_bytes(b"pending-page-bytes")
    destination_stat = new_dir.stat()
    mock_redis.get = AsyncMock(return_value=b"1")
    hashed_paths: list[str] = []

    def spy(path):
        hashed_paths.append(path.name)
        return _sha256(path)

    with ExitStack() as stack:
        for p in _move_patches(db_session_factory, library_root, MagicMock(side_effect=spy)):
            stack.enter_context(p)
        result = await reconcile_library_path_job(
            {"redis": mock_redis},
            old_paths=[str(old_dir)],
            new_path=str(new_dir),
            destination_device=destination_stat.st_dev,
            destination_inode=destination_stat.st_ino,
            watcher_origin=True,
        )

    assert result["status"] == "moved", result
    assert result["gallery_id"] == gallery_id
    assert hashed_paths.count("002.jpg") == 0, "the destination copy of a pending page is not hashed"


async def _seed_link_gallery(db_session, root, source_dir, *, status):
    image = source_dir / "001.jpg"
    source_id = source_dir.name
    await db_session.execute(
        text("INSERT INTO users (username, password_hash, role) VALUES ('missed-user', 'hash', 'admin')")
    )
    user_id = (await db_session.execute(text("SELECT id FROM users WHERE username='missed-user'"))).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO library_paths (path, label, pattern, import_mode, enabled, monitor) "
            "VALUES (:path, 'root', '{title}', 'link', 1, 1)"
        ),
        {"path": str(root)},
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, import_mode, library_path, source_path, "
            "download_status) VALUES ('local', :source_id, 'User title', 1, 'link', :root, :source_path, :status)"
        ),
        {"source_id": source_id, "root": str(root), "source_path": str(source_dir), "status": status},
    )
    gallery_id = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": source_id})
    ).scalar_one()
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, external_path, ref_count) "
            "VALUES (:sha, :size, '.jpg', 'external', :path, 1)"
        ),
        {"sha": sha, "size": image.stat().st_size, "path": str(image)},
    )
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
        {"sha": sha, "path": str(image)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path) "
            "VALUES (:gallery_id, 1, '001.jpg', :sha, :path)"
        ),
        {"gallery_id": gallery_id, "sha": sha, "path": str(image)},
    )
    await db_session.execute(
        text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (:user_id, :gallery_id)"),
        {"user_id": user_id, "gallery_id": gallery_id},
    )
    await db_session.commit()
    return gallery_id


def _missed_move_patches(db_session_factory, library_root):
    scan_settings = MagicMock(library_monitor_enabled=True, data_library_path=str(library_root))
    return (
        patch("worker.scan.AsyncSessionLocal", db_session_factory),
        patch("worker.scan.get_all_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.get_monitored_library_paths", new=AsyncMock(return_value=[])),
        patch("worker.scan.settings", scan_settings),
        patch("services.cas.settings", MagicMock(data_library_path=str(library_root))),
        patch("core.events.emit_safe", new_callable=AsyncMock),
        patch("core.queue.enqueue", new_callable=AsyncMock),
    )


@pytest.mark.parametrize("status", ["complete", "missing"], ids=["before-hold", "already-held"])
async def test_auto_discover_reconnects_folder_rename_the_watcher_missed(
    status, db_session, db_session_factory, mock_redis, tmp_path
):
    from worker.scan import auto_discover_job

    root = tmp_path / "root"
    old_dir = root / "old-name"
    old_dir.mkdir(parents=True)
    (old_dir / "001.jpg").write_bytes(b"missed-move")
    gallery_id = await _seed_link_gallery(db_session, root, old_dir, status=status)
    new_dir = root / "new-name"
    old_dir.rename(new_dir)

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as enqueue:
        result = await auto_discover_job({"redis": mock_redis})

    assert result["discovered"] == 0
    enqueue.assert_not_awaited()
    row = (
        await db_session.execute(
            text("SELECT source_id, source_path, title, download_status FROM galleries WHERE id=:g"), {"g": gallery_id}
        )
    ).one()
    assert tuple(row) == ("new-name", str(new_dir), "User title", "complete")
    assert (await db_session.execute(text("SELECT COUNT(*) FROM galleries"))).scalar_one() == 1
    assert (
        await db_session.execute(text("SELECT COUNT(*) FROM user_favorites WHERE gallery_id=:g"), {"g": gallery_id})
    ).scalar_one() == 1
    image_path = (
        await db_session.execute(text("SELECT external_path FROM images WHERE gallery_id=:g"), {"g": gallery_id})
    ).scalar_one()
    assert image_path == str(new_dir / "001.jpg")


async def test_auto_discover_imports_unrelated_folder_while_a_source_is_vanished(
    db_session, db_session_factory, mock_redis, tmp_path
):
    from worker.scan import auto_discover_job

    root = tmp_path / "root"
    gone_dir = root / "gone"
    gone_dir.mkdir(parents=True)
    (gone_dir / "001.jpg").write_bytes(b"gone-content")
    gallery_id = await _seed_link_gallery(db_session, root, gone_dir, status="complete")
    (gone_dir / "001.jpg").unlink()
    gone_dir.rmdir()
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "001.jpg").write_bytes(b"different-longer-content")

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    # The upsert's ON CONFLICT target only exists on Postgres; this test is about what reaches it.
    discover = AsyncMock(return_value=None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with patch("worker.scan._discover_single_library_dir", discover):
            await auto_discover_job({"redis": mock_redis})

    discover.assert_awaited_once()
    assert discover.await_args.args[2] == unrelated
    old_source_id = (
        await db_session.execute(text("SELECT source_id FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).scalar_one()
    assert old_source_id == "gone"


async def test_auto_discover_skips_folder_matching_two_vanished_galleries(
    db_session, db_session_factory, mock_redis, tmp_path
):
    """Fail closed (ADR 0009): an ambiguous match must not split off a third gallery."""
    from worker.scan import auto_discover_job

    root = tmp_path / "root"
    first = root / "first"
    first.mkdir(parents=True)
    (first / "001.jpg").write_bytes(b"same-bytes")
    gallery_id = await _seed_link_gallery(db_session, root, first, status="complete")
    sha = hashlib.sha256(b"same-bytes").hexdigest()
    second = root / "second"
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, import_mode, library_path, source_path, "
            "download_status) VALUES ('local', 'second', 'Twin', 1, 'link', :root, :source_path, 'complete')"
        ),
        {"root": str(root), "source_path": str(second)},
    )
    twin_id = (await db_session.execute(text("SELECT id FROM galleries WHERE source_id='second'"))).scalar_one()
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :path)"),
        {"sha": sha, "path": str(second / "001.jpg")},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path) "
            "VALUES (:g, 1, '001.jpg', :sha, :path)"
        ),
        {"g": twin_id, "sha": sha, "path": str(second / "001.jpg")},
    )
    await db_session.commit()
    new_dir = root / "renamed"
    first.rename(new_dir)

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as enqueue:
        result = await auto_discover_job({"redis": mock_redis})

    assert result["discovered"] == 0
    enqueue.assert_not_awaited()
    assert (await db_session.execute(text("SELECT COUNT(*) FROM galleries"))).scalar_one() == 2
    source_id = (
        await db_session.execute(text("SELECT source_id FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).scalar_one()
    assert source_id == "first"


async def test_auto_discover_does_not_treat_sources_under_an_empty_root_as_vanished(
    db_session, db_session_factory, mock_redis, tmp_path
):
    """An unmounted root makes every source look gone; nothing there is a rename."""
    from worker.scan import auto_discover_job

    root = tmp_path / "root"
    mounted_dir = root / "album"
    mounted_dir.mkdir(parents=True)
    (mounted_dir / "001.jpg").write_bytes(b"same-bytes")
    gallery_id = await _seed_link_gallery(db_session, root, mounted_dir, status="complete")
    other_root = tmp_path / "other-root"
    copied = other_root / "album-copy"
    copied.mkdir(parents=True)
    (copied / "001.jpg").write_bytes(b"same-bytes")
    await db_session.execute(
        text(
            "INSERT INTO library_paths (path, label, pattern, import_mode, enabled, monitor) "
            "VALUES (:path, 'other', '{title}', 'link', 1, 1)"
        ),
        {"path": str(other_root)},
    )
    await db_session.commit()
    (mounted_dir / "001.jpg").unlink()
    mounted_dir.rmdir()

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    discover = AsyncMock(return_value=None)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with patch("worker.scan._discover_single_library_dir", discover):
            await auto_discover_job({"redis": mock_redis})

    discover.assert_awaited_once()
    assert discover.await_args.args[2] == copied
    source_id = (
        await db_session.execute(text("SELECT source_id FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).scalar_one()
    assert source_id == "album"


async def test_rescan_by_path_reconnects_folder_rename_the_watcher_missed(
    db_session, db_session_factory, mock_redis, tmp_path
):
    """A file event inside the renamed folder must not fork a second gallery."""
    from worker.scan import rescan_by_path_job

    root = tmp_path / "root"
    old_dir = root / "old-name"
    old_dir.mkdir(parents=True)
    (old_dir / "001.jpg").write_bytes(b"missed-move")
    gallery_id = await _seed_link_gallery(db_session, root, old_dir, status="complete")
    new_dir = root / "new-name"
    old_dir.rename(new_dir)

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as enqueue:
        result = await rescan_by_path_job({"redis": mock_redis}, str(new_dir))

    assert result["status"] == "moved"
    assert result["gallery_id"] == gallery_id
    enqueue.assert_not_awaited()


async def test_second_rename_after_a_missed_one_reconnects_through_the_move_job(
    db_session, db_session_factory, mock_redis, tmp_path
):
    """A -> B while the worker was down, B -> C once it is back: the job only knows B."""
    from worker.scan import move_library_path_job

    root = tmp_path / "root"
    old_dir = root / "first-name"
    old_dir.mkdir(parents=True)
    (old_dir / "001.jpg").write_bytes(b"missed-move")
    gallery_id = await _seed_link_gallery(db_session, root, old_dir, status="complete")
    final_dir = root / "third-name"
    old_dir.rename(final_dir)

    patches = _missed_move_patches(db_session_factory, tmp_path / "library")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as enqueue:
        result = await move_library_path_job({"redis": mock_redis}, str(root / "second-name"), str(final_dir))

    assert result["status"] == "moved"
    assert result["gallery_id"] == gallery_id
    enqueue.assert_not_awaited()
