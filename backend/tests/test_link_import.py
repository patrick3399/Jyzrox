"""Link-mode local import: register now, hash later (ADR 0015)."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import text

from tests.test_link_sync import _env, _gallery, _images, _write, layout  # noqa: F401


async def test_link_import_registers_pages_and_leaves_gallery_importing(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    _write(source / "002.jpg", b"two")
    gallery_id = await _gallery(db_session, source, root, status="importing")

    with _env(db_session_factory, library) as enqueue, patch("worker.importer.AsyncSessionLocal", db_session_factory):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "done", "processed": 2, "import_failures": []}
    rows = await _images(db_session, gallery_id)
    assert [(row[1], row[3]) for row in rows] == [("001.jpg", None), ("002.jpg", None)]
    status, pages = (
        await db_session.execute(text("SELECT download_status, pages FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).one()
    assert (status, pages) == ("importing", 2), "the gallery stays importing until the hash pass ends"
    assert [call.args[0] for call in enqueue.await_args_list] == ["link_hash_job"]
    enqueue.hasher.assert_not_called()


async def test_link_import_folder_without_media_marks_gallery_failed(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    (source / "notes.txt").write_text("not media")
    gallery_id = await _gallery(db_session, source, root, status="importing")

    with _env(db_session_factory, library) as enqueue, patch("worker.importer.AsyncSessionLocal", db_session_factory):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "failed", "error": "no supported files found"}
    status = (
        await db_session.execute(text("SELECT download_status FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).scalar_one()
    assert status == "failed"
    enqueue.assert_not_awaited()


async def test_link_import_files_just_copied_are_registered_instead_of_failing_the_gallery(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    _write(source / "001.jpg", b"one", age_s=0)
    gallery_id = await _gallery(db_session, source, root, status="importing")

    async def wait_for_files_to_settle(_seconds):
        _write(source / "001.jpg", b"one")

    with (
        _env(db_session_factory, library),
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.asyncio.sleep", side_effect=wait_for_files_to_settle) as sleep,
    ):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "done", "processed": 1, "import_failures": []}
    sleep.assert_awaited_once()
    status, pages = (
        await db_session.execute(text("SELECT download_status, pages FROM galleries WHERE id=:g"), {"g": gallery_id})
    ).one()
    assert (status, pages) == ("importing", 1)


async def test_link_import_files_never_settling_reports_them_as_still_being_written(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    _write(source / "001.jpg", b"one", age_s=0)
    gallery_id = await _gallery(db_session, source, root, status="importing")

    async def file_keeps_changing(_seconds):
        _write(source / "001.jpg", b"more", age_s=0)

    with (
        _env(db_session_factory, library),
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.asyncio.sleep", side_effect=file_keeps_changing) as sleep,
    ):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "failed", "error": "files are still being written"}
    assert 0 < sleep.await_count < 10, "the wait must be bounded: it holds an ingest slot"


async def test_link_import_sync_lock_held_by_another_pass_is_retried(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root, status="importing")
    mock_redis.set = AsyncMock(side_effect=[None, True])

    with (
        _env(db_session_factory, library),
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "done", "processed": 1, "import_failures": []}


async def test_link_import_trashed_gallery_is_skipped(
    db_session,
    db_session_factory,
    mock_redis,
    layout,  # noqa: F811
):
    from worker.importer import local_import_job

    root, source, library = layout
    _write(source / "001.jpg", b"one")
    gallery_id = await _gallery(db_session, source, root, status="importing")
    await db_session.execute(text("UPDATE galleries SET deleted_at=CURRENT_TIMESTAMP WHERE id=:g"), {"g": gallery_id})
    await db_session.commit()

    with (
        _env(db_session_factory, library) as enqueue,
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.sync_link_gallery", new_callable=AsyncMock) as sync,
    ):
        result = await local_import_job({"redis": mock_redis}, str(source), "link", gallery_id)

    assert result == {"status": "skipped_trashed", "gallery_id": gallery_id}
    sync.assert_not_awaited()
    enqueue.assert_not_awaited()
    assert await _images(db_session, gallery_id) == []


async def test_batch_import_creates_gallery_as_importing(db_session, db_session_factory, mock_redis, tmp_path):
    from worker.importer import batch_import_job

    root = tmp_path / "root"
    folder = root / "album"
    folder.mkdir(parents=True)

    with (
        patch("worker.importer.AsyncSessionLocal", db_session_factory),
        patch("worker.importer.local_import_job", new=AsyncMock(return_value={"status": "done"})),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        result = await batch_import_job(
            {"redis": mock_redis},
            root_dir=str(root),
            mode="link",
            galleries=[{"path": str(folder), "title": "Album"}],
            batch_id="batch-importing",
            user_id=1,
        )

    assert result["completed"] == 1
    row = (
        await db_session.execute(
            text("SELECT download_status, import_mode FROM galleries WHERE source_id='album' AND source='local'")
        )
    ).one()
    assert tuple(row) == ("importing", "link")
