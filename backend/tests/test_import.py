"""
Tests for import endpoints (/api/import/*).

Uses the `client` fixture (pre-authenticated). The import router:
- Validates root_dir against library paths and internal data dir
- Enqueues an ARQ job via request.app.state.arq (mocked in conftest lifespan)
- Reads/writes Redis for batch progress data
- For link mode, upserts into LibraryPath table via async_session

The import router imports `async_session` lazily (inside the function body),
so we patch `core.database.async_session` to redirect DB writes to the test DB.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# POST /api/import/batch/scan — scan directory with pattern
# ---------------------------------------------------------------------------


class TestBatchScan:
    """POST /api/import/batch/scan — scan root_dir using a pattern."""

    async def test_scan_with_title_pattern(self, client, mock_redis):
        """Pattern {title} should match all immediate subdirs that contain media."""
        walk_data = [
            ("/mnt/test_lib/root", ["gallery1", "gallery2"], []),
            ("/mnt/test_lib/root/gallery1", [], ["1.jpg", "2.png"]),
            ("/mnt/test_lib/root/gallery2", [], ["a.webp"]),
        ]
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
            patch("os.walk", return_value=iter(walk_data)),
        ):
            resp = await client.post(
                "/api/import/batch/scan",
                json={"root_dir": "/mnt/test_lib/root", "pattern": "{title}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert "unmatched" in data

        titles = {m["title"] for m in data["matches"]}
        assert "gallery1" in titles
        assert "gallery2" in titles

        match1 = next(m for m in data["matches"] if m["title"] == "gallery1")
        assert match1["file_count"] == 2
        match2 = next(m for m in data["matches"] if m["title"] == "gallery2")
        assert match2["file_count"] == 1

        for m in data["matches"]:
            assert m["artist"] is None

    async def test_scan_with_artist_title_pattern(self, client, mock_redis):
        """Pattern {artist}/{title} should extract both artist and title groups."""
        walk_data = [
            ("/mnt/test_lib/root", ["artist_name"], []),
            ("/mnt/test_lib/root/artist_name", ["gallery_name"], []),
            ("/mnt/test_lib/root/artist_name/gallery_name", [], ["page1.jpg", "page2.jpg", "page3.png"]),
        ]
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
            patch("os.walk", return_value=iter(walk_data)),
        ):
            resp = await client.post(
                "/api/import/batch/scan",
                json={"root_dir": "/mnt/test_lib/root", "pattern": "{artist}/{title}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        assert match["artist"] == "artist_name"
        assert match["title"] == "gallery_name"
        assert match["file_count"] == 3
        assert match["rel_path"] == "artist_name/gallery_name"

    async def test_scan_unmatched_directories(self, client, mock_redis):
        """Directories that do not match the pattern appear in unmatched."""
        walk_data = [
            ("/mnt/test_lib/root", ["deep"], []),
            ("/mnt/test_lib/root/deep", ["nested"], []),
            ("/mnt/test_lib/root/deep/nested", [], ["img.jpg"]),
        ]
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
            patch("os.walk", return_value=iter(walk_data)),
        ):
            # Pattern {title} only matches one level deep — "deep/nested" should not match
            resp = await client.post(
                "/api/import/batch/scan",
                json={"root_dir": "/mnt/test_lib/root", "pattern": "{title}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        unmatched_paths = {u["rel_path"] for u in data["unmatched"]}
        assert "deep/nested" in unmatched_paths

    async def test_scan_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post(
            "/api/import/batch/scan",
            json={"root_dir": "/mnt/test_lib/root", "pattern": "{title}"},
        )
        assert resp.status_code == 401

    async def test_scan_rejects_internal_path(self, client):
        """root_dir inside data_gallery_path should return 400."""
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("os.path.realpath", side_effect=lambda p: p),
        ):
            resp = await client.post(
                "/api/import/batch/scan",
                json={"root_dir": "/data/gallery/subdir", "pattern": "{title}"},
            )

        assert resp.status_code == 400
        assert "internal" in resp.json()["detail"].lower() or "download" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/import/batch/start — start batch import job
# ---------------------------------------------------------------------------


class TestBatchStart:
    """POST /api/import/batch/start — enqueue a batch import job."""

    async def test_start_copy_mode(self, client, mock_redis):
        """Valid copy-mode request should store progress in Redis and enqueue a job."""
        from main import app

        galleries = [
            {"path": "/mnt/test_lib/root/gallery1", "artist": None, "title": "Gallery One"},
            {"path": "/mnt/test_lib/root/gallery2", "artist": None, "title": "Gallery Two"},
        ]
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
        ):
            resp = await client.post(
                "/api/import/batch/start",
                json={"root_dir": "/mnt/test_lib/root", "mode": "copy", "galleries": galleries},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "batch_id" in data
        assert data["total"] == 2
        assert isinstance(data["batch_id"], str)
        assert len(data["batch_id"]) == 36  # UUID format

        # setex is called twice: once for batch data, once for batch owner
        mock_redis.setex.assert_called()
        # Verify at least one call was for the batch progress key
        batch_keys = [call[0][0] for call in mock_redis.setex.call_args_list]
        assert any(k.startswith("import:batch:") for k in batch_keys)

        app.state.arq.enqueue_job.assert_called()
        enqueue_call = app.state.arq.enqueue_job.call_args
        assert enqueue_call[0][0] == "batch_import_job"

    async def test_start_link_mode_registers_library(self, client, mock_redis):
        """Link mode should upsert the root_dir into the LibraryPath table."""
        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = MagicMock(return_value=mock_session_ctx)

        galleries = [
            {"path": "/mnt/test_lib/root/art1", "artist": "Artist", "title": "Work One"},
        ]
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
            patch("routers.import_router.async_session", mock_session_factory),
        ):
            resp = await client.post(
                "/api/import/batch/start",
                json={"root_dir": "/mnt/test_lib/root", "mode": "link", "galleries": galleries},
            )

        assert resp.status_code == 200
        # The mock session should have been entered (link mode triggers DB upsert)
        mock_session_ctx.__aenter__.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    async def test_start_invalid_mode_returns_400(self, client, mock_redis):
        """Mode other than copy or link should return 400."""
        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("routers.import_router.get_redis", return_value=mock_redis),
        ):
            resp = await client.post(
                "/api/import/batch/start",
                json={
                    "root_dir": "/mnt/test_lib/root",
                    "mode": "move",
                    "galleries": [{"path": "/mnt/test_lib/root/g1", "artist": None, "title": "G1"}],
                },
            )

        assert resp.status_code == 400
        assert "mode" in resp.json()["detail"].lower() or "copy" in resp.json()["detail"].lower() or "link" in resp.json()["detail"].lower()

    async def test_start_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post(
            "/api/import/batch/start",
            json={"root_dir": "/mnt/test_lib/root", "mode": "copy", "galleries": []},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/batch/progress/{batch_id} — poll batch import progress
# ---------------------------------------------------------------------------


class TestBatchProgress:
    """GET /api/import/batch/progress/{batch_id} — batch progress polling."""

    async def test_progress_unknown_batch(self, client, mock_redis):
        """Unknown batch_id should return 404 (not found in Redis)."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/batch/progress/nonexistent-batch-id")

        assert resp.status_code == 404

    async def test_progress_with_redis_data(self, client, mock_redis):
        """Existing batch_id should return parsed progress data from Redis."""
        batch_id = "test-batch-uuid-1234"
        progress_payload = {
            "total": 10,
            "completed": 4,
            "failed": 1,
            "status": "running",
            "current_gallery_id": None,
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(progress_payload).encode())
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get(f"/api/import/batch/progress/{batch_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["total"] == 10
        assert data["completed"] == 4
        assert data["failed"] == 1

        mock_redis.get.assert_called_once_with(f"import:batch:{batch_id}")

    async def test_progress_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/batch/progress/some-batch-id")
        assert resp.status_code == 401


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
