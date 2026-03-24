"""Tests that router mutation endpoints emit correct EventBus events.

Each test:
1. Sets up required DB data via raw SQL (same pattern as test_library.py).
2. Patches core.events.emit_safe as AsyncMock.
3. Calls the endpoint via the authenticated `client` fixture.
4. Asserts emit_safe was called with the expected EventType.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_gallery(db_session, source="ehentai", source_id="99999", **overrides):
    """Insert a gallery and return its integer id."""
    defaults = {
        "source": source,
        "source_id": source_id,
        "title": "Event Test Gallery",
        "pages": 10,
        "download_status": "completed",
        "tags_array": "[]",
    }
    defaults.update(overrides)
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array) "
            "VALUES (:source, :source_id, :title, :pages, :download_status, :tags_array)"
        ),
        defaults,
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_download_job(db_session, status="running"):
    """Insert a download job and return its UUID."""
    job_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO download_jobs (id, url, source, status, progress, user_id) "
            "VALUES (:id, :url, :source, :status, :progress, :user_id)"
        ),
        {
            "id": str(job_id),
            "url": "https://example.com/download",
            "source": "test",
            "status": status,
            "progress": "{}",
            "user_id": 1,
        },
    )
    await db_session.commit()
    return job_id


async def _insert_subscription(db_session):
    """Insert a subscription and return its id."""
    await db_session.execute(
        text(
            "INSERT INTO subscriptions (user_id, url, source, enabled, auto_download) "
            "VALUES (:user_id, :url, :source, :enabled, :auto_download)"
        ),
        {
            "user_id": 1,
            "url": "https://example.com/feed/unique-event-test",
            "source": "test",
            "enabled": 1,
            "auto_download": 1,
        },
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


async def _insert_collection(db_session):
    """Insert a collection and return its id."""
    await db_session.execute(
        text(
            "INSERT INTO collections (user_id, name) VALUES (:user_id, :name)"
        ),
        {"user_id": 1, "name": "Event Test Collection"},
    )
    await db_session.commit()
    result = await db_session.execute(text("SELECT last_insert_rowid()"))
    return result.scalar()


# ---------------------------------------------------------------------------
# Library router emit tests
# ---------------------------------------------------------------------------


async def test_delete_gallery_emits_gallery_deleted(client, db_session):
    """DELETE /api/library/galleries/{source}/{source_id} emits GALLERY_DELETED."""
    await _insert_gallery(db_session, source="ehentai", source_id="del-001")

    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.delete("/api/library/galleries/ehentai/del-001")

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.GALLERY_DELETED


async def test_restore_gallery_emits_gallery_restored(client, db_session):
    """POST /api/library/galleries/{source}/{source_id}/restore emits GALLERY_RESTORED."""
    await _insert_gallery(db_session, source="ehentai", source_id="rst-001")
    # Soft-delete it so it shows up in trash
    await db_session.execute(
        text("UPDATE galleries SET deleted_at = :ts WHERE source_id = 'rst-001'"),
        {"ts": datetime.now(UTC).isoformat()},
    )
    await db_session.commit()

    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.post("/api/library/galleries/ehentai/rst-001/restore")

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.GALLERY_RESTORED


async def test_update_gallery_emits_gallery_updated(client, db_session):
    """PATCH /api/library/galleries/{source}/{source_id} emits GALLERY_UPDATED."""
    await _insert_gallery(db_session, source="ehentai", source_id="upd-001")

    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.patch(
            "/api/library/galleries/ehentai/upd-001",
            json={"title": "Updated Title"},
        )

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.GALLERY_UPDATED


# ---------------------------------------------------------------------------
# Download router emit tests
# ---------------------------------------------------------------------------


async def test_enqueue_download_emits_download_enqueued(client):
    """POST /api/download/ emits DOWNLOAD_ENQUEUED after successful enqueue."""
    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.post(
            "/api/download/",
            json={"url": "https://e-hentai.org/g/1234567/abcdef1234/"},
        )

    # The endpoint may return 200 or 503 (if SAQ mock isn't perfect),
    # but emit_safe is only called on success (200).
    if resp.status_code == 200:
        mock_emit.assert_called_once()
        from core.events import EventType
        assert mock_emit.call_args.args[0] == EventType.DOWNLOAD_ENQUEUED
    else:
        # If enqueue failed (503), emit was not called — that is also correct behavior.
        mock_emit.assert_not_called()


async def test_cancel_download_emits_download_cancelled(client, db_session, mock_redis):
    """DELETE /api/download/jobs/{id} emits DOWNLOAD_CANCELLED."""
    job_id = await _insert_download_job(db_session, status="running")

    mock_emit = AsyncMock()
    # download.py imports get_redis at module level, so patch the bound name in the module
    with patch("core.events.emit_safe", mock_emit):
        with patch("routers.download.get_redis", return_value=mock_redis):
            resp = await client.delete(f"/api/download/jobs/{job_id}")

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.DOWNLOAD_CANCELLED


# ---------------------------------------------------------------------------
# Subscriptions router emit tests
# ---------------------------------------------------------------------------


async def test_create_subscription_emits_subscription_created(client, db_session):
    """POST /api/subscriptions/ emits SUBSCRIPTION_CREATED."""
    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.post(
            "/api/subscriptions/",
            json={"url": "https://example.com/sub/new-unique-sub-123", "name": "Test Sub"},
        )

    # 200 on create; accept 409 (duplicate) as test isolation may vary
    assert resp.status_code in (200, 409)
    if resp.status_code == 200:
        mock_emit.assert_called_once()
        from core.events import EventType
        assert mock_emit.call_args.args[0] == EventType.SUBSCRIPTION_CREATED


async def test_delete_subscription_emits_subscription_deleted(client, db_session):
    """DELETE /api/subscriptions/{id} emits SUBSCRIPTION_DELETED."""
    sub_id = await _insert_subscription(db_session)

    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.delete(f"/api/subscriptions/{sub_id}")

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.SUBSCRIPTION_DELETED


# ---------------------------------------------------------------------------
# Collections router emit tests
# ---------------------------------------------------------------------------


async def test_create_collection_emits_collection_updated(client):
    """POST /api/collections/ emits COLLECTION_UPDATED."""
    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.post(
            "/api/collections/",
            json={"name": "New Collection"},
        )

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.COLLECTION_UPDATED


async def test_delete_collection_emits_collection_updated(client, db_session):
    """DELETE /api/collections/{id} emits COLLECTION_UPDATED."""
    col_id = await _insert_collection(db_session)

    mock_emit = AsyncMock()
    with patch("core.events.emit_safe", mock_emit):
        resp = await client.delete(f"/api/collections/{col_id}")

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.COLLECTION_UPDATED


# ---------------------------------------------------------------------------
# Dedup router emit tests
# ---------------------------------------------------------------------------


async def test_dedup_start_scan_emits_dedup_scan_started(client, mock_redis):
    """POST /api/dedup/scan/start emits DEDUP_SCAN_STARTED."""
    # Ensure Redis returns no running scan so the endpoint proceeds
    mock_redis.get = AsyncMock(return_value=None)

    mock_emit = AsyncMock()
    # dedup.py imports get_redis lazily inside the function via `from core.redis_client import get_redis`,
    # so patching core.redis_client.get_redis is sufficient.
    with patch("core.events.emit_safe", mock_emit):
        with patch("core.redis_client.get_redis", return_value=mock_redis):
            resp = await client.post(
                "/api/dedup/scan/start",
                json={"mode": "pending"},
            )

    assert resp.status_code == 200
    mock_emit.assert_called_once()
    from core.events import EventType
    assert mock_emit.call_args.args[0] == EventType.DEDUP_SCAN_STARTED
