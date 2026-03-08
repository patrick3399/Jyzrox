"""
Tests for import endpoints (/api/import/*).

Uses the `client` fixture (pre-authenticated). The import router:
- Creates a gallery row via raw SQL (async_session from core.database)
- Enqueues an ARQ job via request.app.state.arq (mocked in conftest lifespan)
- Reads Redis for progress data

The import router imports `async_session` lazily (inside the function body),
so we patch `core.database.async_session` to redirect DB writes to the test DB.
"""

import json
import os
from unittest.mock import AsyncMock, patch

from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _gallery_count(db_session) -> int:
    """Return the number of galleries in the test DB."""
    result = await db_session.execute(text("SELECT COUNT(*) FROM galleries"))
    return result.scalar()


# ---------------------------------------------------------------------------
# POST /api/import/ — enqueue import job
# ---------------------------------------------------------------------------


class TestStartImport:
    """POST /api/import/ — start a local import job."""

    async def test_import_valid_link_mode(self, client, db_session, db_session_factory):
        """Valid request with mode=link should create a gallery and enqueue a job.

        The import router imports async_session lazily inside the function body via
        `from core.database import async_session`. Since core.database is a fake
        module injected into sys.modules before any imports, we patch its
        `async_session` attribute directly on that module object.
        """
        import sys

        fake_db = sys.modules["core.database"]
        original = fake_db.async_session
        fake_db.async_session = db_session_factory
        try:
            gallery_path = "/data/gallery/my_series"
            with (
                patch("core.config.settings.data_gallery_path", "/data/gallery"),
                patch("os.path.realpath", side_effect=lambda p: p),
            ):
                resp = await client.post(
                    "/api/import/",
                    json={"source_dir": gallery_path, "mode": "link"},
                )
        finally:
            fake_db.async_session = original

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "enqueued"
        assert "gallery_id" in data
        assert isinstance(data["gallery_id"], int)

    async def test_import_valid_copy_mode(self, client, db_session, db_session_factory):
        """Valid request with mode=copy should also succeed."""
        import sys

        fake_db = sys.modules["core.database"]
        original = fake_db.async_session
        fake_db.async_session = db_session_factory
        try:
            gallery_path = "/data/gallery/another_series"
            with (
                patch("core.config.settings.data_gallery_path", "/data/gallery"),
                patch("os.path.realpath", side_effect=lambda p: p),
            ):
                resp = await client.post(
                    "/api/import/",
                    json={"source_dir": gallery_path, "mode": "copy"},
                )
        finally:
            fake_db.async_session = original

        assert resp.status_code == 200
        assert resp.json()["status"] == "enqueued"

    async def test_import_with_metadata(self, client, db_session, db_session_factory):
        """Request with metadata should pass the title to the gallery row."""
        import sys

        fake_db = sys.modules["core.database"]
        original = fake_db.async_session
        fake_db.async_session = db_session_factory
        try:
            gallery_path = "/data/gallery/titled_gallery"
            with (
                patch("core.config.settings.data_gallery_path", "/data/gallery"),
                patch("os.path.realpath", side_effect=lambda p: p),
            ):
                resp = await client.post(
                    "/api/import/",
                    json={
                        "source_dir": gallery_path,
                        "mode": "link",
                        "metadata": {"title": "My Custom Title"},
                    },
                )
        finally:
            fake_db.async_session = original

        assert resp.status_code == 200
        gallery_id = resp.json()["gallery_id"]

        # Verify title was stored in the test DB
        row = await db_session.execute(
            text("SELECT title FROM galleries WHERE id = :id"), {"id": gallery_id}
        )
        title = row.scalar()
        assert title == "My Custom Title"

    async def test_import_invalid_mode_returns_400(self, client):
        """Unsupported import mode should return 400."""
        resp = await client.post(
            "/api/import/",
            json={"source_dir": "/data/gallery/foo", "mode": "move"},
        )
        assert resp.status_code == 400
        assert "Invalid import mode" in resp.json()["detail"]

    async def test_import_path_outside_gallery_returns_400(self, client):
        """source_dir outside the allowed gallery path should return 400."""
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("os.path.realpath", side_effect=lambda p: p),
        ):
            resp = await client.post(
                "/api/import/",
                json={"source_dir": "/tmp/evil_dir", "mode": "link"},
            )
        assert resp.status_code == 400
        assert "gallery path" in resp.json()["detail"].lower()

    async def test_import_path_traversal_returns_400(self, client):
        """Path traversal attempt should be rejected."""
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("os.path.realpath", side_effect=os.path.normpath),
        ):
            resp = await client.post(
                "/api/import/",
                json={"source_dir": "/data/gallery/../../../etc/passwd", "mode": "link"},
            )
        assert resp.status_code == 400

    async def test_import_enqueues_arq_job(self, client, db_session, db_session_factory):
        """After a valid import request the ARQ job should be enqueued."""
        import sys
        from main import app

        fake_db = sys.modules["core.database"]
        original = fake_db.async_session
        fake_db.async_session = db_session_factory
        try:
            gallery_path = "/data/gallery/arq_test"
            with (
                patch("core.config.settings.data_gallery_path", "/data/gallery"),
                patch("os.path.realpath", side_effect=lambda p: p),
            ):
                resp = await client.post(
                    "/api/import/",
                    json={"source_dir": gallery_path, "mode": "link"},
                )
        finally:
            fake_db.async_session = original

        assert resp.status_code == 200
        app.state.arq.enqueue_job.assert_called()
        call_args = app.state.arq.enqueue_job.call_args
        assert call_args[0][0] == "local_import_job"

    async def test_import_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post(
            "/api/import/",
            json={"source_dir": "/data/gallery/foo", "mode": "link"},
        )
        assert resp.status_code == 401

    async def test_import_missing_source_dir_returns_422(self, client):
        """Missing source_dir field should return 422 validation error."""
        resp = await client.post("/api/import/", json={"mode": "link"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/import/progress/{gallery_id} — poll import progress
# ---------------------------------------------------------------------------


class TestGetImportProgress:
    """GET /api/import/progress/{gallery_id} — import progress polling."""

    async def test_progress_unknown_gallery(self, client, mock_redis):
        """Gallery with no Redis progress data should return status=unknown."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/progress/9999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gallery_id"] == 9999
        assert data["status"] == "unknown"

    async def test_progress_with_redis_data(self, client, mock_redis):
        """Gallery with Redis progress data should return parsed status."""
        progress_data = {"status": "running", "current": 5, "total": 20}
        mock_redis.get = AsyncMock(return_value=json.dumps(progress_data).encode())
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/progress/42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gallery_id"] == 42
        assert data["status"] == "running"
        assert data["current"] == 5
        assert data["total"] == 20

    async def test_progress_completed_status(self, client, mock_redis):
        """Completed import should return status=completed in progress data."""
        progress_data = {"status": "completed", "current": 10, "total": 10}
        mock_redis.get = AsyncMock(return_value=json.dumps(progress_data).encode())
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/progress/7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    async def test_progress_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/progress/1")
        assert resp.status_code == 401
