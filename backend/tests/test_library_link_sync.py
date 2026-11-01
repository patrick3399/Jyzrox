"""POST /api/library/galleries/{source}/{source_id}/sync (ADR 0014, ADR 0015)."""

from unittest.mock import ANY, AsyncMock, patch

from sqlalchemy import text


async def _insert(db_session, source_id: str, *, import_mode: str | None, source_path: str | None) -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, import_mode, source_path, download_status, pages) "
            "VALUES ('local', :sid, 'T', :mode, :path, 'complete', 3)"
        ),
        {"sid": source_id, "mode": import_mode, "path": source_path},
    )
    await db_session.commit()
    return (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": source_id})
    ).scalar_one()


async def test_sync_link_gallery_returns_service_result(client, db_session):
    from services.link_sync import LinkSyncResult

    gallery_id = await _insert(db_session, "linked", import_mode="link", source_path="/mnt/lib/linked")
    sync = AsyncMock(return_value=LinkSyncResult(status="synced", added=2, pending=2, pages=5))

    with (
        patch("routers.library.sync_link_gallery", sync),
        patch("routers.library.get_redis", return_value=AsyncMock()),
    ):
        response = await client.post("/api/library/galleries/local/linked/sync")

    assert response.status_code == 200
    assert response.json() == {
        "status": "synced",
        "changed": True,
        "added": 2,
        "removed": 0,
        "renamed": 0,
        "replaced": 0,
        "pending": 2,
        "pages": 5,
    }
    assert sync.await_args.args == (gallery_id,)


async def test_sync_endpoint_never_passes_hash_limits(client, db_session):
    """The sync is stat-only (ADR 0015): no inline hashing budget, no deferral, no endpoint-side enqueue."""
    from services.link_sync import LinkSyncResult

    gallery_id = await _insert(db_session, "nolimits", import_mode="link", source_path="/mnt/lib/nolimits")
    sync = AsyncMock(return_value=LinkSyncResult(status="synced", added=300, pending=300, pages=303))

    with (
        patch("routers.library.sync_link_gallery", sync),
        patch("routers.library.get_redis", return_value=AsyncMock()),
        patch("core.queue.enqueue", new_callable=AsyncMock) as enqueue,
    ):
        response = await client.post("/api/library/galleries/local/nolimits/sync")

    assert response.json()["pending"] == 300
    assert sync.await_args.args == (gallery_id,)
    assert sync.await_args.kwargs == {"redis": ANY}
    enqueue.assert_not_awaited()


async def test_sync_non_link_gallery_does_no_filesystem_work(client, db_session):
    await _insert(db_session, "copied", import_mode="copy", source_path=None)
    sync = AsyncMock()

    with patch("routers.library.sync_link_gallery", sync):
        response = await client.post("/api/library/galleries/local/copied/sync")

    assert response.status_code == 200
    assert response.json()["status"] == "not_link"
    assert response.json()["changed"] is False
    sync.assert_not_awaited()


async def test_sync_unknown_gallery_is_404(client):
    response = await client.post("/api/library/galleries/local/nope/sync")

    assert response.status_code == 404


async def test_sync_requires_authentication(unauthed_client):
    response = await unauthed_client.post("/api/library/galleries/local/linked/sync")

    assert response.status_code == 401
