"""
Tests for import endpoints (/api/import/*).

Uses the `client` fixture (pre-authenticated). The import router:
- Validates root_dir against library paths and internal data dir
- Enqueues a job via core.queue.enqueue (mocked in conftest lifespan)
- Reads/writes Redis for batch progress data
- For link mode, upserts into LibraryPath table via async_session

The import router imports `async_session` lazily (inside the function body),
so we patch `core.database.async_session` to redirect DB writes to the test DB.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

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
            patch("os.sep", "/"),
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

        def _posix_relpath(path, start):
            # Strip start prefix and return forward-slash relative path
            path = path.replace("\\", "/")
            start = start.replace("\\", "/")
            if path == start:
                return "."
            if path.startswith(start.rstrip("/") + "/"):
                return path[len(start.rstrip("/")) + 1:]
            return path

        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.relpath", side_effect=_posix_relpath),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("os.sep", "/"),
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

        def _posix_relpath(path, start):
            path = path.replace("\\", "/")
            start = start.replace("\\", "/")
            if path == start:
                return "."
            if path.startswith(start.rstrip("/") + "/"):
                return path[len(start.rstrip("/")) + 1:]
            return path

        with (
            patch("core.config.settings.data_gallery_path", "/data/gallery"),
            patch("core.config.settings.library_base_path", "/mnt"),
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=["/mnt/test_lib"])),
            patch("os.path.realpath", side_effect=lambda p: p),
            patch("os.path.relpath", side_effect=_posix_relpath),
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
            patch("os.sep", "/"),
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
            patch("os.sep", "/"),
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
            patch("os.sep", "/"),
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

        app.state.enqueue.assert_called()
        enqueue_call = app.state.enqueue.call_args
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
            patch("os.sep", "/"),
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
            patch("os.sep", "/"),
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


# ---------------------------------------------------------------------------
# Worker function helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock async session that works as an async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    # scalar_one returns a gallery_id by default
    scalar_result = MagicMock()
    scalar_result.scalar_one.return_value = 42
    scalar_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=scalar_result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)
    return session


def _make_session_factory(session):
    """Wrap a mock session as a callable context-manager factory."""
    factory = MagicMock(return_value=session)
    return factory


def _make_ctx():
    """Return a minimal SAQ worker ctx dict."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    return {"redis": redis}


# ---------------------------------------------------------------------------
# TestImportJob — tests for worker.importer.import_job
# ---------------------------------------------------------------------------


class TestImportJob:
    """Unit tests for import_job worker function."""

    async def test_non_directory_path_returns_error(self, tmp_path):
        """A path that is not a directory should return failed status immediately."""
        from worker.importer import import_job

        non_dir = tmp_path / "not_a_dir.txt"
        non_dir.write_text("hello")

        result = await import_job(_make_ctx(), str(non_dir))
        assert result["status"] == "failed"
        assert "not a directory" in result["error"]

    async def test_no_media_files_returns_error(self, tmp_path):
        """A directory with no media files and no metadata should return failed status."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "empty_gallery"
        gallery_dir.mkdir()
        # Put only a text file — not a media file
        (gallery_dir / "readme.txt").write_text("nothing here")

        mock_session = _make_mock_session()

        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer._validate_image_magic", return_value=False),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
        ):
            result = await import_job(_make_ctx(), str(gallery_dir))

        assert result["status"] == "failed"
        assert "no media files" in result["error"]

    async def test_excluded_blob_is_skipped(self, tmp_path):
        """Files whose sha256 appears in excluded_blobs should not be stored."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "test_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        fixed_hash = "deadbeef" * 8  # 64-char hex

        # Session returns excluded hash so the file should be skipped entirely
        mock_session = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = [fixed_hash]

        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 99

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return gallery_scalar  # gallery upsert
            return excl_result         # excluded blobs query

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_store_blob = AsyncMock()
        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        mock_parser = MagicMock()
        mock_parser.get_parser = MagicMock(return_value=None)

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", mock_store_blob),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
        ):
            # No media files remain after exclusion, so expect failed
            result = await import_job(_make_ctx(), str(gallery_dir))

        # store_blob should never be called — excluded blob was skipped
        mock_store_blob.assert_not_called()

    async def test_thumbnail_job_enqueued_on_success(self, tmp_path):
        """On successful import, thumbnail_job should be enqueued via ctx redis."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "success_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        fixed_hash = "aabbccdd" * 8

        mock_session = _make_mock_session()
        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 7
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return gallery_scalar
            return excl_result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer._upsert_tags", AsyncMock()),
            patch("shutil.rmtree"),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            result = await import_job(ctx, str(gallery_dir))

        assert result["status"] == "done"
        assert result["gallery_id"] == 7
        mock_enqueue.assert_any_call("thumbnail_job", gallery_id=7)

    async def test_source_url_stored_in_gallery(self, tmp_path):
        """source_url parameter should be passed through to the gallery upsert values."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "url_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        fixed_hash = "11223344" * 8
        captured_values = {}

        mock_session = _make_mock_session()
        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 55
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Capture the compiled statement's parameters
                try:
                    captured_values.update(stmt.compile().params)
                except Exception:
                    pass
                return gallery_scalar
            return excl_result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        ctx = _make_ctx()
        test_url = "https://example.com/gallery/123"

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer._upsert_tags", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            result = await import_job(ctx, str(gallery_dir), source_url=test_url)

        assert result["status"] == "done"

    async def test_tag_job_enqueued_when_model_enabled(self, tmp_path):
        """When tag_model_enabled is True, tag_job should also be enqueued."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "tag_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        fixed_hash = "99aabbcc" * 8

        mock_session = _make_mock_session()
        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 88
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return gallery_scalar
            return excl_result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer._upsert_tags", AsyncMock()),
            patch("worker.importer.settings") as mock_settings,
            patch("shutil.rmtree"),
            patch("core.queue.enqueue", new_callable=AsyncMock) as mock_enqueue,
        ):
            mock_settings.tag_model_enabled = True
            result = await import_job(ctx, str(gallery_dir))

        assert result["status"] == "done"
        enqueue_calls = [c.args[0] for c in mock_enqueue.call_args_list]
        assert "thumbnail_job" in enqueue_calls
        assert "tag_job" in enqueue_calls

    async def test_user_id_stored_in_gallery(self, tmp_path):
        """user_id parameter should be forwarded to gallery_values."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "user_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        fixed_hash = "fedcba98" * 8

        mock_session = _make_mock_session()
        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 33
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return gallery_scalar
            return excl_result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        _site_cfg = MagicMock()
        _site_cfg.source_id = "gallery_dl"
        _site_cfg.source_id_fields = []

        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer._upsert_tags", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            result = await import_job(ctx, str(gallery_dir), user_id=5)

        assert result["status"] == "done"

    async def test_metadata_json_is_read_when_present(self, tmp_path):
        """A gallery-dl JSON metadata file should be parsed for gallery info."""
        from worker.importer import import_job

        gallery_dir = tmp_path / "meta_gallery"
        gallery_dir.mkdir()
        img = gallery_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        meta = {
            "category": "pixiv",
            "title": "Test Title",
            "id": "12345",
        }
        (gallery_dir / "info.json").write_text(json.dumps(meta))

        fixed_hash = "cafebabe" * 8

        mock_session = _make_mock_session()
        gallery_scalar = MagicMock()
        gallery_scalar.scalar_one.return_value = 21
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def _execute_side_effect(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return gallery_scalar
            return excl_result

        mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        _site_cfg = MagicMock()
        _site_cfg.source_id = "pixiv"
        _site_cfg.source_id_fields = ["id"]

        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("worker.importer._sha256", return_value=fixed_hash),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_site_cfg),
            patch("plugins.registry.plugin_registry.get_parser", return_value=None),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer._upsert_tags", AsyncMock()),
            patch("shutil.rmtree"),
        ):
            result = await import_job(ctx, str(gallery_dir))

        assert result["status"] == "done"
        assert result["gallery_id"] == 21


# ---------------------------------------------------------------------------
# TestLocalImportJob — tests for worker.importer.local_import_job
# ---------------------------------------------------------------------------


class TestLocalImportJob:
    """Unit tests for local_import_job worker function."""

    async def test_non_directory_returns_error(self, tmp_path):
        """A source_dir that is not a directory should return failed status."""
        from worker.importer import local_import_job

        fake_path = str(tmp_path / "nonexistent")

        result = await local_import_job(_make_ctx(), fake_path, "copy", gallery_id=1)
        assert result["status"] == "failed"
        assert "not a directory" in result["error"]

    async def test_gallery_not_found_in_db_returns_error(self, tmp_path):
        """When gallery does not exist in DB, the job should return failed."""
        from worker.importer import local_import_job

        src = tmp_path / "src"
        src.mkdir()
        img = src / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_session = _make_mock_session()
        mock_session.get = AsyncMock(return_value=None)  # gallery not found

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer._validate_image_magic", return_value=True),
        ):
            result = await local_import_job(_make_ctx(), str(src), "copy", gallery_id=999)

        assert result["status"] == "failed"
        assert "gallery not found" in result["error"]

    async def test_no_supported_files_returns_failed(self, tmp_path):
        """Directory with no media files should return failed status."""
        from worker.importer import local_import_job

        src = tmp_path / "empty_src"
        src.mkdir()
        (src / "readme.txt").write_text("nothing useful")

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "test_src"

        mock_session = _make_mock_session()
        mock_session.get = AsyncMock(return_value=mock_gallery)

        with (
            patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)),
            patch("worker.importer._validate_image_magic", return_value=False),
        ):
            result = await local_import_job(_make_ctx(), str(src), "copy", gallery_id=1)

        assert result["status"] == "failed"
        assert "no supported files" in result["error"]

    async def test_copy_mode_calls_store_blob_without_external(self, tmp_path):
        """Copy mode should call store_blob without storage='external'."""
        from worker.importer import local_import_job

        src = tmp_path / "copy_src"
        src.mkdir()
        img = src / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "copy_src"

        fixed_hash = "aaccee00" * 8
        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        # Three session contexts are opened: gallery lookup, excluded blobs, file processing
        mock_sess1 = _make_mock_session()
        mock_sess1.get = AsyncMock(return_value=mock_gallery)

        mock_sess2 = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []
        mock_sess2.execute = AsyncMock(return_value=excl_result)

        mock_sess3 = _make_mock_session()
        img_result = MagicMock()
        img_result.scalar_one.return_value = None
        mock_sess3.execute = AsyncMock(return_value=img_result)
        mock_sess3.get = AsyncMock(return_value=mock_gallery)

        sessions = iter([mock_sess1, mock_sess2, mock_sess3])

        def _factory():
            return next(sessions)

        mock_store = AsyncMock(return_value=mock_blob)
        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_factory),
            patch("worker.importer.store_blob", mock_store),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer.settings") as mock_settings,
        ):
            mock_settings.tag_model_enabled = False
            result = await local_import_job(ctx, str(src), "copy", gallery_id=1)

        assert result["status"] == "done"
        assert result["processed"] == 1
        # store_blob should be called without storage='external'
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args[1] if mock_store.call_args[1] else {}
        assert call_kwargs.get("storage") != "external"

    async def test_link_mode_calls_store_blob_with_external_storage(self, tmp_path):
        """Link mode should call store_blob with storage='external'."""
        from worker.importer import local_import_job

        src = tmp_path / "link_src"
        src.mkdir()
        img = src / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "link_src"

        fixed_hash = "11223344" * 8
        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        mock_sess1 = _make_mock_session()
        mock_sess1.get = AsyncMock(return_value=mock_gallery)

        mock_sess2 = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []
        mock_sess2.execute = AsyncMock(return_value=excl_result)

        mock_sess3 = _make_mock_session()
        img_result = MagicMock()
        img_result.scalar_one.return_value = None
        mock_sess3.execute = AsyncMock(return_value=img_result)
        mock_sess3.get = AsyncMock(return_value=mock_gallery)

        sessions = iter([mock_sess1, mock_sess2, mock_sess3])

        def _factory():
            return next(sessions)

        mock_store = AsyncMock(return_value=mock_blob)
        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_factory),
            patch("worker.importer.store_blob", mock_store),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer.settings") as mock_settings,
        ):
            mock_settings.tag_model_enabled = False
            result = await local_import_job(ctx, str(src), "link", gallery_id=1)

        assert result["status"] == "done"
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args[1] if mock_store.call_args[1] else {}
        assert call_kwargs.get("storage") == "external"

    async def test_excluded_blob_skipped_in_local_import(self, tmp_path):
        """Files matching excluded_blobs sha256 should be skipped during local import."""
        from worker.importer import local_import_job

        src = tmp_path / "excl_src"
        src.mkdir()
        img = src / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "excl_src"

        fixed_hash = "excluded0" * 7 + "1234567"

        mock_sess1 = _make_mock_session()
        mock_sess1.get = AsyncMock(return_value=mock_gallery)

        mock_sess2 = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = [fixed_hash]
        mock_sess2.execute = AsyncMock(return_value=excl_result)

        mock_sess3 = _make_mock_session()
        mock_sess3.get = AsyncMock(return_value=mock_gallery)

        sessions = iter([mock_sess1, mock_sess2, mock_sess3])

        def _factory():
            return next(sessions)

        mock_store = AsyncMock()
        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_factory),
            patch("worker.importer.store_blob", mock_store),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer.settings") as mock_settings,
        ):
            mock_settings.tag_model_enabled = False
            result = await local_import_job(ctx, str(src), "copy", gallery_id=1)

        assert result["status"] == "done"
        assert result["processed"] == 0
        mock_store.assert_not_called()

    async def test_progress_written_to_redis(self, tmp_path):
        """Progress setex calls should be made to Redis during and after import."""
        from worker.importer import local_import_job

        src = tmp_path / "progress_src"
        src.mkdir()
        for i in range(3):
            img = src / f"page{i}.jpg"
            img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "progress_src"

        fixed_hash = "00112233" * 8
        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        mock_sess1 = _make_mock_session()
        mock_sess1.get = AsyncMock(return_value=mock_gallery)

        mock_sess2 = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []
        mock_sess2.execute = AsyncMock(return_value=excl_result)

        mock_sess3 = _make_mock_session()
        img_result = MagicMock()
        img_result.scalar_one.return_value = None
        mock_sess3.execute = AsyncMock(return_value=img_result)
        mock_sess3.get = AsyncMock(return_value=mock_gallery)

        sessions = iter([mock_sess1, mock_sess2, mock_sess3])

        def _factory():
            return next(sessions)

        ctx = _make_ctx()

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_factory),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer.settings") as mock_settings,
        ):
            mock_settings.tag_model_enabled = False
            result = await local_import_job(ctx, str(src), "copy", gallery_id=10)

        assert result["status"] == "done"
        # setex should have been called at least once for progress and once for done
        assert ctx["redis"].setex.call_count >= 2
        # Final call should write status=done
        final_call_args = ctx["redis"].setex.call_args_list[-1]
        key = final_call_args[0][0]
        payload = json.loads(final_call_args[0][2])
        assert key == "import:progress:10"
        assert payload["status"] == "done"


# ---------------------------------------------------------------------------
# TestBatchImportJob — tests for worker.importer.batch_import_job
# ---------------------------------------------------------------------------


class TestBatchImportJob:
    """Unit tests for batch_import_job worker function."""

    async def test_empty_galleries_returns_zero_completed(self, tmp_path):
        """An empty galleries list should return status done with 0 completed."""
        from worker.importer import batch_import_job

        ctx = _make_ctx()
        result = await batch_import_job(
            ctx,
            root_dir=str(tmp_path),
            mode="copy",
            galleries=[],
            batch_id="test-batch-empty",
            user_id=1,
        )

        assert result["status"] == "done"
        assert result["completed"] == 0
        assert result["failed"] == 0

    async def test_batch_id_used_in_redis_keys(self, tmp_path):
        """Progress Redis keys should include the batch_id."""
        from worker.importer import batch_import_job

        ctx = _make_ctx()
        batch_id = "my-unique-batch-42"

        result = await batch_import_job(
            ctx,
            root_dir=str(tmp_path),
            mode="copy",
            galleries=[],
            batch_id=batch_id,
            user_id=1,
        )

        assert result["status"] == "done"
        # The final setex call should use the batch key
        all_keys = [c[0][0] for c in ctx["redis"].setex.call_args_list]
        assert any(batch_id in k for k in all_keys)

    async def test_failed_gallery_increments_failed_count(self, tmp_path):
        """A gallery whose local_import_job raises should increment failed count."""
        from worker.importer import batch_import_job

        gallery_dir = tmp_path / "bad_gallery"
        gallery_dir.mkdir()

        mock_session = _make_mock_session()
        # scalar_one raises to simulate INSERT failure
        err_result = MagicMock()
        err_result.scalar_one.side_effect = Exception("DB error")
        mock_session.execute = AsyncMock(return_value=err_result)

        ctx = _make_ctx()

        galleries = [{"path": str(gallery_dir), "artist": None, "title": "Bad Gallery"}]

        with patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)):
            result = await batch_import_job(
                ctx,
                root_dir=str(tmp_path),
                mode="copy",
                galleries=galleries,
                batch_id="batch-err",
                user_id=1,
            )

        assert result["status"] == "done"
        assert result["failed"] == 1
        assert result["completed"] == 0

    async def test_one_success_one_failure_correct_counts(self, tmp_path):
        """One succeeding and one failing gallery should report correct counts."""
        from worker.importer import batch_import_job

        # Good gallery: has an image
        good_dir = tmp_path / "good_gallery"
        good_dir.mkdir()
        img = good_dir / "page1.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        # Bad gallery: path doesn't exist, so local_import_job will fail
        bad_dir = tmp_path / "bad_gallery"
        # Intentionally NOT created

        fixed_hash = "55667788" * 8
        mock_blob = MagicMock()
        mock_blob.sha256 = fixed_hash

        mock_gallery = MagicMock()
        mock_gallery.source = "local"
        mock_gallery.source_id = "good_gallery"

        # Session for INSERT of good gallery
        insert_result = MagicMock()
        insert_result.scalar_one.return_value = 77

        mock_insert_sess = _make_mock_session()
        mock_insert_sess.execute = AsyncMock(return_value=insert_result)

        # Three sessions for local_import_job of good gallery
        mock_lg1 = _make_mock_session()
        mock_lg1.get = AsyncMock(return_value=mock_gallery)

        mock_lg2 = _make_mock_session()
        excl_result = MagicMock()
        excl_result.scalars.return_value.all.return_value = []
        mock_lg2.execute = AsyncMock(return_value=excl_result)

        mock_lg3 = _make_mock_session()
        img_result = MagicMock()
        img_result.scalar_one.return_value = None
        mock_lg3.execute = AsyncMock(return_value=img_result)
        mock_lg3.get = AsyncMock(return_value=mock_gallery)

        # Session for INSERT of bad gallery raises
        mock_bad_sess = _make_mock_session()
        err_result = MagicMock()
        err_result.scalar_one.side_effect = Exception("insert failed")
        mock_bad_sess.execute = AsyncMock(return_value=err_result)

        sessions = iter([mock_insert_sess, mock_lg1, mock_lg2, mock_lg3, mock_bad_sess])

        def _factory():
            return next(sessions)

        ctx = _make_ctx()

        galleries = [
            {"path": str(good_dir), "artist": None, "title": "Good Gallery"},
            {"path": str(bad_dir), "artist": None, "title": "Bad Gallery"},
        ]

        with (
            patch("worker.importer.AsyncSessionLocal", side_effect=_factory),
            patch("worker.importer.store_blob", AsyncMock(return_value=mock_blob)),
            patch("worker.importer.create_library_symlink", AsyncMock()),
            patch("worker.importer._validate_image_magic", return_value=True),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fixed_hash),
            patch("worker.importer.settings") as mock_settings,
        ):
            mock_settings.tag_model_enabled = False
            result = await batch_import_job(
                ctx,
                root_dir=str(tmp_path),
                mode="copy",
                galleries=galleries,
                batch_id="batch-mixed",
                user_id=2,
            )

        assert result["status"] == "done"
        assert result["completed"] == 1
        assert result["failed"] == 1

    async def test_progress_updated_after_each_gallery(self, tmp_path):
        """setex should be called after each gallery is processed."""
        from worker.importer import batch_import_job

        ctx = _make_ctx()
        batch_id = "batch-progress-test"

        # Three galleries, all will fail (paths don't exist)
        galleries = [
            {"path": str(tmp_path / f"g{i}"), "artist": None, "title": f"Gallery {i}"}
            for i in range(3)
        ]

        mock_session = _make_mock_session()
        err_result = MagicMock()
        err_result.scalar_one.side_effect = Exception("no dir")
        mock_session.execute = AsyncMock(return_value=err_result)

        with patch("worker.importer.AsyncSessionLocal", _make_session_factory(mock_session)):
            result = await batch_import_job(
                ctx,
                root_dir=str(tmp_path),
                mode="copy",
                galleries=galleries,
                batch_id=batch_id,
                user_id=1,
            )

        assert result["failed"] == 3
        # setex is called once per gallery (after error) + once final = 4 calls total
        assert ctx["redis"].setex.call_count >= 4


# ---------------------------------------------------------------------------
# GET /api/import/recent — recently imported galleries
# ---------------------------------------------------------------------------


class TestRecentImports:
    """GET /api/import/recent — recently added local galleries."""

    async def test_recent_imports_empty_returns_empty_list(self, client, db_session_factory):
        """With no local galleries, should return an empty list."""
        with patch("routers.import_router.async_session", db_session_factory):
            resp = await client.get("/api/import/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    async def test_recent_imports_returns_local_galleries(self, client, db_session, db_session_factory):
        """Should return local-source galleries sorted by added_at descending."""
        from sqlalchemy import text

        for i, sid in enumerate(["recent01", "recent02"]):
            await db_session.execute(
                text(
                    "INSERT INTO galleries (source, source_id, title, download_status, tags_array) "
                    "VALUES ('local', :sid, :title, 'completed', '[]')"
                ),
                {"sid": sid, "title": f"Local Gallery {i}"},
            )
        # Also insert a non-local gallery that should NOT appear
        await db_session.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, download_status, tags_array) "
                "VALUES ('pixiv', 'px001', 'Pixiv Work', 'completed', '[]')"
            )
        )
        await db_session.commit()

        with patch("routers.import_router.async_session", db_session_factory):
            resp = await client.get("/api/import/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        sources = {g["id"] for g in data}
        titles = [g["title"] for g in data]
        assert all("Local Gallery" in t for t in titles)

    async def test_recent_imports_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/recent")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/libraries — list library paths
# ---------------------------------------------------------------------------


class TestListLibraries:
    """GET /api/import/libraries — all configured library paths."""

    async def test_list_libraries_returns_paths(self, client, db_session_factory, mock_redis):
        """Should return a list of configured library paths."""
        with (
            patch(
                "routers.import_router.get_all_library_paths",
                AsyncMock(return_value=["/mnt/lib1"]),
            ),
            patch("routers.import_router.async_session", db_session_factory),
        ):
            resp = await client.get("/api/import/libraries")
        assert resp.status_code == 200
        data = resp.json()
        # Response is a list of library path objects
        assert isinstance(data, list)

    async def test_list_libraries_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/libraries")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/rescan/status — rescan progress
# ---------------------------------------------------------------------------


class TestRescanStatus:
    """GET /api/import/rescan/status — file monitor / rescan status."""

    async def test_rescan_status_not_running(self, client, mock_redis):
        """With no rescan in progress, running=False should be returned."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/rescan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    async def test_rescan_status_running(self, client, mock_redis):
        """With an active rescan stored in Redis, running=True should be returned."""
        import json as _json
        mock_redis.get = AsyncMock(
            return_value=_json.dumps({"status": "running", "current": 3, "total": 10}).encode()
        )
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/rescan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True

    async def test_rescan_status_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/rescan/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/scan-settings — scan schedule settings
# ---------------------------------------------------------------------------


class TestScanSettings:
    """GET /api/import/scan-settings — retrieve scan schedule config."""

    async def test_get_scan_settings_returns_defaults(self, client, mock_redis):
        """With no Redis overrides, default scan settings should be returned."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/scan-settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "interval_hours" in data
        assert isinstance(data["enabled"], bool)
        assert isinstance(data["interval_hours"], int)

    async def test_patch_scan_settings_invalid_interval_returns_400(self, client, mock_redis):
        """interval_hours outside [6, 168] should return 400."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.patch(
                "/api/import/scan-settings",
                json={"interval_hours": 2},
            )
        assert resp.status_code == 400

    async def test_patch_scan_settings_valid_interval(self, client, mock_redis):
        """Valid interval_hours should be accepted and returned."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.patch(
                "/api/import/scan-settings",
                json={"interval_hours": 24},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_hours"] == 24


# ---------------------------------------------------------------------------
# POST /api/import/rescan — enqueue full library rescan
# ---------------------------------------------------------------------------


class TestRescan:
    """POST /api/import/rescan — enqueue rescan job."""

    async def test_rescan_enqueues_job(self, client, mock_redis):
        """POST /api/import/rescan should enqueue rescan_library_job and return status=enqueued."""
        from main import app

        resp = await client.post("/api/import/rescan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "enqueued"
        app.state.enqueue.assert_any_call("rescan_library_job")

    async def test_rescan_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post("/api/import/rescan")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/rescan/status — rescan progress from Redis
# ---------------------------------------------------------------------------


class TestRescanStatus:
    """GET /api/import/rescan/status — rescan progress."""

    async def test_rescan_status_not_running_when_no_redis_data(self, client, mock_redis):
        """No Redis data should return running=False."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/rescan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    async def test_rescan_status_running_when_redis_says_running(self, client, mock_redis):
        """Redis data with status=running should return running=True."""
        progress = json.dumps({"status": "running", "current": 5, "total": 100})
        mock_redis.get = AsyncMock(return_value=progress.encode())
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/rescan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["current"] == 5
        assert data["total"] == 100

    async def test_rescan_status_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/rescan/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/import/rescan/cancel — cancel running rescan
# ---------------------------------------------------------------------------


class TestRescanCancel:
    """POST /api/import/rescan/cancel — cancel rescan."""

    async def test_rescan_cancel_returns_cancelling(self, client, mock_redis):
        """POST /api/import/rescan/cancel should set Redis key and return status=cancelling."""
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.post("/api/import/rescan/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelling"
        mock_redis.set.assert_called()

    async def test_rescan_cancel_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post("/api/import/rescan/cancel")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/monitor/status — file watcher status
# ---------------------------------------------------------------------------


class TestMonitorStatus:
    """GET /api/import/monitor/status — file watcher status."""

    async def test_monitor_status_no_redis_data_returns_defaults(self, client, mock_redis):
        """No Redis watcher:status data should return running=False."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/monitor/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "watched_paths" in data
        assert data["running"] is False

    async def test_monitor_status_with_redis_data(self, client, mock_redis):
        """Redis data should be reflected in the response."""
        watcher_data = json.dumps({"running": True, "paths": ["/mnt/library"]})
        mock_redis.get = AsyncMock(return_value=watcher_data.encode())
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.get("/api/import/monitor/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert "/mnt/library" in data["watched_paths"]

    async def test_monitor_status_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/monitor/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/import/monitor/toggle — toggle file watcher
# ---------------------------------------------------------------------------


class TestMonitorToggle:
    """POST /api/import/monitor/toggle — toggle file watcher on/off."""

    async def test_monitor_toggle_enable(self, client, mock_redis):
        """Toggling monitor on should set watcher:enabled and return status=enabled."""
        mock_redis.get = AsyncMock(return_value=None)
        from main import app

        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.post(
                "/api/import/monitor/toggle",
                json={"enabled": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "enabled"
        mock_redis.set.assert_called()
        app.state.enqueue.assert_any_call("toggle_watcher_job", enabled=True)

    async def test_monitor_toggle_disable(self, client, mock_redis):
        """Toggling monitor off should return status=disabled."""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("routers.import_router.get_redis", return_value=mock_redis):
            resp = await client.post(
                "/api/import/monitor/toggle",
                json={"enabled": False},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

    async def test_monitor_toggle_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post(
            "/api/import/monitor/toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/import/recent — recent local gallery imports
# ---------------------------------------------------------------------------


class TestRecentImports:
    """GET /api/import/recent — recently added local galleries."""

    async def test_recent_imports_empty_returns_empty_list(self, client, db_session_factory):
        """No local galleries in DB should return empty list."""
        with patch("routers.import_router.async_session", db_session_factory):
            resp = await client.get("/api/import/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_recent_imports_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/recent")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET/POST /api/import/libraries — library path management
# ---------------------------------------------------------------------------


class TestLibraries:
    """GET /api/import/libraries and POST /api/import/libraries."""

    async def test_list_libraries_returns_list(self, client, mock_redis, db_session_factory):
        """GET /api/import/libraries should return a list of library paths."""
        with (
            patch("routers.import_router.get_all_library_paths", AsyncMock(return_value=[])),
            patch("routers.import_router.async_session", db_session_factory),
        ):
            resp = await client.get("/api/import/libraries")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_list_libraries_requires_auth(self, unauthed_client):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/import/libraries")
        assert resp.status_code == 401

    async def test_add_library_nonexistent_path_returns_400(self, client):
        """Adding a library path that doesn't exist on disk should return 400."""
        with (
            patch("routers.import_router.async_session"),
            patch("os.path.realpath", side_effect=lambda p: p),
        ):
            resp = await client.post(
                "/api/import/libraries",
                json={"path": "/nonexistent/path/that/does/not/exist"},
            )
        assert resp.status_code == 400
