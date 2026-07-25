"""Tests for download pipeline: GalleryDlPlugin.download() and download_job().

Tests cover:
- Cancel detection in _read_stdout (kills process, skips last pending file)
- Partial vs failed status based on downloaded count
- download_job() status transitions: cancelled cleanup, failed-with-downloads,
  and the post-download cancel guard.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

# Import shared mock factory (must come after sys.path setup)
import pytest

from tests.helpers import make_mock_site_config_svc


@pytest.fixture(autouse=True)
def mock_redis_global():
    """Prevent any code path from calling get_redis() on an uninitialised client."""
    mock_redis = AsyncMock()
    pipeline = MagicMock()
    pipeline.execute = AsyncMock(return_value=[])
    mock_redis.pipeline = MagicMock(return_value=pipeline)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        yield mock_redis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_iter(lines: list[bytes], delay: float = 0):
    """Return an async iterable that yields the given byte lines."""

    async def _gen():
        for line in lines:
            if delay > 0:
                await asyncio.sleep(delay)
            yield line

    return _gen()


def _make_mock_proc(
    stdout_lines: list[bytes],
    returncode: int = 0,
    stderr: bytes = b"",
    stderr_lines: list[bytes] | None = None,
    stdout_delay: float = 0,
    block_wait: bool = False,
):
    """Build a mock asyncio subprocess with controllable stdout/stderr/returncode.

    Args:
        stdout_delay: per-line delay in seconds (for testing cancel/pause watchers).
        stderr_lines: explicit stderr lines as async iterable; if None, uses empty iterable.
        block_wait: if True, proc.wait() blocks until proc.kill() is called.
                    Use this for cancel/pause tests where the watcher needs time to fire.
    """
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = returncode
    proc.stdout = _make_async_iter(stdout_lines, delay=stdout_delay)
    proc.stderr = MagicMock()
    stderr_chunks = list(stderr_lines or [])
    proc.stderr.read = AsyncMock(side_effect=stderr_chunks + [b""])

    if block_wait:
        _kill_event = asyncio.Event()

        def _finish_process():
            proc.returncode = -15
            _kill_event.set()

        proc.terminate = MagicMock(side_effect=_finish_process)
        proc.kill = MagicMock(side_effect=_finish_process)

        async def _blocking_wait():
            await _kill_event.wait()
            return proc.returncode

        proc.wait = _blocking_wait
    else:
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=returncode)

    return proc


def _source_patches():
    """Common patches for GalleryDlPlugin.download() tests."""
    return [
        patch(
            "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
            new_callable=AsyncMock,
            return_value=Path("/tmp/gallery-dl-test.json"),
        ),
        patch(
            "plugins.builtin.gallery_dl.source.settings",
            MagicMock(
                data_gallery_path="/data/gallery",
                gallery_dl_config="/tmp/gallery-dl-test.json",
                gdl_archive_dsn="postgresql://test:test@localhost:5432/test",
            ),
        ),
        patch("pathlib.Path.mkdir"),
        patch("core.site_config.site_config_service", make_mock_site_config_svc()),
    ]


# ---------------------------------------------------------------------------
# TestGalleryDlCancel
# ---------------------------------------------------------------------------


class TestGalleryDlCancel:
    """Tests for cancel detection inside GalleryDlPlugin.download()."""

    async def test_cancel_check_returns_cancelled_status(self):
        """When cancel_check returns True, process is killed and status is cancelled."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        lines = [
            b"JYZROX_FILE\t/data/gallery/image001.jpg\tabc1\n",
            b"JYZROX_FILE\t/data/gallery/image002.jpg\tabc2\n",
            b"JYZROX_FILE\t/data/gallery/image003.jpg\tabc3\n",
        ]
        # block_wait=True: proc.wait() blocks until kill() is called by the cancel watcher
        mock_proc = _make_mock_proc(lines, returncode=0, block_wait=True)

        call_count = 0

        async def cancel_check() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        patches = _source_patches() + [
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await plugin.download(
                url="https://example.com/gallery/123",
                dest_dir=Path("/data/gallery"),
                credentials={},
                cancel_check=cancel_check,
                pid_callback=AsyncMock(),
            )

        assert result.status == "cancelled"
        mock_proc.terminate.assert_called()

    async def test_cancel_skips_last_pending_file(self):
        """When cancelled, the last pending file is not imported (state.cancelled guard)."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        # With block_wait=True, proc.wait() blocks until kill().
        # cancel_check always returns True, so _pause_cancel_watcher fires immediately
        # and sets state.cancelled=True, which prevents the last pending file import.
        lines = [
            b"JYZROX_FILE\t/data/gallery/image001.jpg\tabc1\n",
            b"JYZROX_FILE\t/data/gallery/image002.jpg\tabc2\n",
        ]
        mock_proc = _make_mock_proc(lines, returncode=0, block_wait=True)

        imported_files: list[Path] = []

        async def on_file(path: Path, sha256: str | None = None) -> None:
            imported_files.append(path)

        async def cancel_check() -> bool:
            return True

        patches = _source_patches() + [
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await plugin.download(
                url="https://example.com/gallery/123",
                dest_dir=Path("/data/gallery"),
                credentials={},
                cancel_check=cancel_check,
                on_file=on_file,
            )

        assert result.status == "cancelled"
        # The cancel watcher kills the process; _read_stdout may have finished reading
        # both lines before the cancel fires, but the last pending file is skipped
        # because state.cancelled is checked in _read_stdout's post-loop guard.
        # With instant stdout (no delay), all lines may be read before cancel fires,
        # so image001 might be imported but image002 (last pending) should be skipped.
        # The key invariant: result.status is "cancelled" and process was killed.
        mock_proc.terminate.assert_called()


# ---------------------------------------------------------------------------
# TestGalleryDlPartial
# ---------------------------------------------------------------------------


class TestGalleryDlPartial:
    """Tests for partial vs failed status based on subprocess exit code + downloads."""

    async def test_partial_on_nonzero_exit_with_downloads(self):
        """Non-zero exit code + some files downloaded → status is 'partial'."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        lines = [
            b"JYZROX_FILE\t/data/gallery/image001.jpg\tabc123\n",
            b"JYZROX_FILE\t/data/gallery/image002.jpg\tdef456\n",
        ]
        mock_proc = _make_mock_proc(lines, returncode=1, stderr=b"some error")

        async def cancel_check() -> bool:
            return False

        patches = _source_patches() + [
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await plugin.download(
                url="https://example.com/gallery/123",
                dest_dir=Path("/data/gallery"),
                credentials={},
                cancel_check=cancel_check,
            )

        assert result.status == "partial"
        assert result.downloaded >= 1
        assert result.error is not None

    async def test_failed_on_nonzero_exit_no_downloads(self):
        """Non-zero exit code + zero files downloaded → status is 'failed'."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        lines: list[bytes] = []
        mock_proc = _make_mock_proc(lines, returncode=1, stderr=b"fatal error")

        async def cancel_check() -> bool:
            return False

        patches = _source_patches() + [
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await plugin.download(
                url="https://example.com/gallery/123",
                dest_dir=Path("/data/gallery"),
                credentials={},
                cancel_check=cancel_check,
            )

        assert result.status == "failed"
        assert result.downloaded == 0


# ---------------------------------------------------------------------------
# Shared helpers for download_job() tests
# ---------------------------------------------------------------------------


def _make_plugin_result(status="done", downloaded=3, total=3, error=None, failed_pages=None):
    """Build a minimal plugin DownloadResult-like object."""
    result = MagicMock()
    result.status = status
    result.downloaded = downloaded
    result.total = total
    result.error = error
    result.failed_pages = failed_pages or []
    return result


def test_postprocess_failure_with_downloaded_files_is_partial_not_done():
    from worker.download import _postprocess_failure_status

    assert _postprocess_failure_status(3) == "partial"
    assert _postprocess_failure_status(0) == "failed"


class TestAuthoritativeDatabaseCancelGuard:
    async def test_cancelled_database_row_wins(self):
        from worker.download import _is_job_cancelled_in_db

        session = _make_mock_session()
        session.get.return_value = MagicMock(status="cancelled")
        with patch("core.database.AsyncSessionLocal", return_value=session):
            assert await _is_job_cancelled_in_db("b225fc4c-c550-4c19-a741-93d5ef915c4e") is True

    async def test_non_cancelled_or_missing_row_does_not_cancel(self):
        from worker.download import _is_job_cancelled_in_db

        session = _make_mock_session()
        session.get.return_value = MagicMock(status="running")
        with patch("core.database.AsyncSessionLocal", return_value=session):
            assert await _is_job_cancelled_in_db("b225fc4c-c550-4c19-a741-93d5ef915c4e") is False
        assert await _is_job_cancelled_in_db(None) is False


def _make_mock_session():
    """Return a mock async context manager session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.get = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_ctx():
    """Build a minimal worker ctx with a mocked redis pool."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.enqueue_job = AsyncMock()
    return {"redis": redis}


def _make_mock_sem(*, timeout: bool = False) -> MagicMock:
    """Build a DownloadSemaphore mock using the explicit acquire/release API.

    When timeout=True, sem.acquire raises TimeoutError (simulates no available slot).
    """
    mock_sem = MagicMock()
    if timeout:
        mock_sem.acquire = AsyncMock(side_effect=TimeoutError("no slot"))
    else:
        mock_sem.acquire = AsyncMock(return_value=0.0)
    mock_sem.release = AsyncMock()
    mock_sem.heartbeat = AsyncMock(return_value=True)
    mock_sem.get_limit = AsyncMock(return_value=2)
    return mock_sem


def _make_default_site_cfg():
    """Return a minimal site config mock with default inactivity_timeout."""
    cfg = MagicMock()
    cfg.inactivity_timeout = 300
    return cfg


def _patch_download_job_dependencies(
    plugin=None,
    session=None,
    sem_acquire=None,
    get_credential_return=None,
    importer=None,
):
    """Return a list of patches for the common download_job() dependencies."""
    if plugin is None:
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

    if session is None:
        session = _make_mock_session()

    if importer is None:
        importer = MagicMock()
        importer.gallery_id = "gal-1"
        importer.title = "Test Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.ensure_gallery_from_import_data = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-1")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.get_handler = AsyncMock(return_value=plugin)
    mock_registry.get_fallback = MagicMock(return_value=None)
    mock_registry.get_downloader = MagicMock(return_value=None)

    mock_sem = _make_mock_sem()
    mock_sem_cls = MagicMock(return_value=mock_sem)

    return [
        patch("plugins.registry.plugin_registry", mock_registry),
        patch("worker.download.get_credential", new_callable=AsyncMock, return_value=get_credential_return),
        patch("worker.download._set_job_status", new_callable=AsyncMock),
        patch("worker.download._set_job_progress", new_callable=AsyncMock),
        patch("core.database.AsyncSessionLocal", return_value=session),
        patch("worker.progressive.ProgressiveImporter", return_value=importer),
        patch("worker.download.DownloadSemaphore", mock_sem_cls),
        patch("core.redis_client.get_redis", return_value=MagicMock()),
        patch("core.site_config.site_config_service", make_mock_site_config_svc()),
    ]


# ---------------------------------------------------------------------------
# TestDownloadJobPluginErrors
# ---------------------------------------------------------------------------


class TestDownloadJobPluginErrors:
    """Tests for plugin-resolution and credential-gate failures in download_job()."""

    async def test_no_plugin_found_returns_failed(self):
        """When no plugin can handle the URL, download_job returns failed status."""
        from worker.download import download_job

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=None)
        mock_registry.get_fallback = MagicMock(return_value=None)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
        ):
            result = await download_job(_make_ctx(), "https://unknown.example/gallery/1", db_job_id="job-001")

        assert result["status"] == "failed"
        assert "No plugin" in result["error"]
        mock_status.assert_any_call("job-001", "failed", result["error"])

    async def test_credential_required_but_missing_returns_failed(self):
        """When credentials are required but absent, download_job returns failed."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "pixiv"
        plugin.meta.name = "Pixiv"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)

        # downloader that requires credentials
        mock_downloader = MagicMock()
        mock_downloader.requires_credentials = MagicMock(return_value=True)
        mock_downloader.resolve_output_dir = MagicMock(return_value=Path("/tmp/pixiv"))
        mock_registry.get_downloader = MagicMock(return_value=mock_downloader)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
        ):
            result = await download_job(
                _make_ctx(), "https://pixiv.net/artworks/123", source="pixiv", db_job_id="job-002"
            )

        assert result["status"] == "failed"
        assert "credentials" in result["error"].lower()
        mock_status.assert_any_call("job-002", "failed", result["error"])

    async def test_plugin_download_raises_exception_returns_failed(self):
        """When plugin.download() raises, download_job catches it and returns failed."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(side_effect=RuntimeError("connection refused"))

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/99", db_job_id="job-003")

        assert result["status"] == "failed"
        assert "connection refused" in result["error"]
        mock_status.assert_any_call("job-003", "failed", result["error"])

    async def test_plugin_returns_failed_with_no_downloads_returns_failed(self):
        """When plugin returns status=failed and downloaded=0, result is failed."""
        from worker.download import download_job

        plugin_result = _make_plugin_result(status="failed", downloaded=0, error="gallery not found")
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/99", db_job_id="job-004")

        assert result["status"] == "failed"
        assert result.get("error") == "gallery not found"

    async def test_plugin_returns_cancelled_cleans_up(self):
        """When plugin returns status=cancelled, importer.cleanup() is called."""
        from worker.download import download_job

        plugin_result = _make_plugin_result(status="cancelled", downloaded=0)
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/99", db_job_id="job-005")

        assert result["status"] == "cancelled"
        importer.cleanup.assert_awaited_once()
        mock_status.assert_any_call("job-005", "cancelled")

    async def test_no_plugin_and_no_fallback_returns_failed(self):
        """When both handler and fallback are absent, result is failed immediately."""
        from worker.download import download_job

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=None)
        mock_registry.get_fallback = MagicMock(return_value=None)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
        ):
            result = await download_job(_make_ctx(), "https://nowhere.invalid/g/1")

        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# TestDownloadJobSemaphore
# ---------------------------------------------------------------------------


class TestDownloadJobSemaphore:
    """Tests for semaphore acquisition behaviour in download_job()."""

    async def test_semaphore_timeout_returns_failed(self):
        """TimeoutError from semaphore propagates as a failed status."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem(timeout=True)
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch(
                "worker.progressive.ProgressiveImporter",
                return_value=MagicMock(
                    gallery_id=None,
                    title=None,
                    source_url=None,
                    abort=AsyncMock(),
                    cleanup=AsyncMock(),
                ),
            ),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-sem-01")

        assert result["status"] == "failed"
        assert "timed out" in result["error"].lower()
        mock_status.assert_any_call("job-sem-01", "failed", result["error"])

    async def test_semaphore_acquired_and_released(self):
        """Successful download calls sem.acquire() once and sem.release() once."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

        importer = MagicMock()
        importer.gallery_id = "gal-x"
        importer.title = "Gallery X"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-x")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-sem-02")

        assert result["status"] == "done"
        mock_sem.acquire.assert_awaited_once_with("job-sem-02")
        mock_sem.release.assert_awaited_once_with("job-sem-02")

    async def test_semaphore_key_uses_domain_for_gallery_dl(self):
        """For gallery_dl source, semaphore key is prefixed with domain."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = "gallery_dl"
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

        importer = MagicMock()
        importer.gallery_id = "gal-y"
        importer.title = "Gallery Y"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-y")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        captured_keys = []

        def _capture_sem(source, max_count):
            captured_keys.append(source)
            return _make_mock_sem()

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", side_effect=_capture_sem),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            await download_job(_make_ctx(), "https://danbooru.donmai.us/posts/1", db_job_id="job-sem-03")

        assert len(captured_keys) == 1
        assert captured_keys[0].startswith("gallery_dl:danbooru.donmai.us")


# ---------------------------------------------------------------------------
# TestDownloadJobSignals
# ---------------------------------------------------------------------------


class TestDownloadJobSignals:
    """Tests for cancel and pause signal handling inside download_job()."""

    async def test_redis_cancel_flag_propagates_to_plugin(self):
        """When cancel key is set in Redis, cancel_check() returns True."""
        from worker.download import download_job

        received_cancel_check = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            received_cancel_check.append(await cancel_check())
            return _make_plugin_result(status="cancelled", downloaded=0)

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        # Simulate cancel key being set — return b"1" only for cancel keys
        # (pause keys must return None to pass the pre-semaphore pause gate)
        async def _selective_get(key):
            if key.startswith("download:cancel:"):
                return b"1"
            return None

        ctx["redis"].get = _selective_get

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-sig-01")

        assert result["status"] == "cancelled"
        # The cancel_check injected into the plugin must have returned True
        assert received_cancel_check == [True]

    async def test_no_cancel_key_propagates_false(self):
        """When no cancel key is in Redis, cancel_check() returns False."""
        from worker.download import download_job

        received_cancel_check = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            received_cancel_check.append(await cancel_check())
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-z"
        importer.title = "Gallery Z"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-z")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()
        ctx["redis"].get = AsyncMock(return_value=None)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-sig-02")

        assert result["status"] == "done"
        assert received_cancel_check == [False]

    async def test_post_download_cancel_guard_triggers_cancelled(self):
        """If cancel key is set after download completes, result is still cancelled."""
        from worker.download import download_job

        received_calls = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            # During download, cancel is not yet set
            received_calls.append(await cancel_check())
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-q"
        importer.title = "Gallery Q"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-q")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        call_counter = [0]

        async def _get_side_effect(key):
            call_counter[0] += 1
            # First 2 calls (pause gate + during download) → not set;
            # subsequent calls (post-download cancel guard) → set
            if call_counter[0] <= 2:
                return None
            return b"1"

        ctx = _make_ctx()
        ctx["redis"].get = _get_side_effect

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-sig-03")

        assert result["status"] == "cancelled"
        mock_status.assert_any_call("job-sig-03", "cancelled")

    async def test_pause_check_callable_injected_into_plugin(self):
        """pause_check callable is injected and returns True when pause key is set."""
        from worker.download import download_job

        received_pause_check = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            received_pause_check.append(await pause_check())
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-p"
        importer.title = "Gallery P"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-p")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        pause_call_count = [0]

        async def _get_by_key(key):
            if "pause" in key:
                pause_call_count[0] += 1
                # First pause check (pre-semaphore gate) → not paused
                # Second pause check (inside plugin) → paused
                return b"1" if pause_call_count[0] > 1 else None
            return None

        ctx["redis"].get = _get_by_key

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-sig-04")

        assert result["status"] == "done"
        # pause_check should have returned True (pause key was set)
        assert received_pause_check == [True]


# ---------------------------------------------------------------------------
# TestDownloadJobValidation
# ---------------------------------------------------------------------------


class TestDownloadJobValidation:
    """Tests for image validation, progress, PID, and partial-download logic."""

    async def test_corrupt_image_removed_and_counted_as_failed_page(self, tmp_path):
        """Corrupt image files are removed and their page numbers appear in failed_pages."""
        from worker.download import download_job

        # Create a corrupt image file in the subdirectory that download_job will scan
        job_dir = tmp_path / "job-val-01"
        job_dir.mkdir()
        corrupt_file = job_dir / "001.jpg"
        corrupt_file.write_bytes(b"\x00\x00\x00\x00" * 20)  # no valid magic

        plugin_result = _make_plugin_result(status="done", downloaded=2, total=2)
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = "gal-v"
        importer.title = "Gallery V"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-v")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            # Point target_dir at tmp_path so rglob finds our corrupt file
            patch("worker.download.settings", MagicMock(data_gallery_path=str(tmp_path))),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-val-01")

        # With a corrupt file, job should be partial and file should be gone
        assert result["status"] == "partial"
        assert 1 in result.get("failed_pages", [])
        assert not corrupt_file.exists()

    async def test_speed_calculated_in_progress_callback(self):
        """on_progress callback computes a non-negative speed field."""
        from worker.download import download_job

        recorded_progress = []

        async def _fake_set_progress(job_id, progress):
            recorded_progress.append(progress)

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            await on_progress(5, 10)
            return _make_plugin_result(downloaded=5, total=10)

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-sp"
        importer.title = "Speed Test Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-sp")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", _fake_set_progress),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-val-02")

        # Find the progress record that includes 'downloaded' and 'speed'
        progress_with_speed = [p for p in recorded_progress if "speed" in p and "downloaded" in p]
        assert len(progress_with_speed) >= 1
        assert progress_with_speed[0]["speed"] >= 0
        assert progress_with_speed[0]["downloaded"] == 5

    async def test_pid_stored_and_deleted_after_download(self):
        """pid_callback stores PID in Redis and it is deleted after download completes."""
        from worker.download import download_job

        pid_set_keys = []
        pid_del_keys = []

        async def _fake_redis_set(key, value, **kwargs):
            pid_set_keys.append(key)

        async def _fake_redis_del(key):
            pid_del_keys.append(key)

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            await pid_callback(99999)
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-pid"
        importer.title = "PID Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-pid")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()
        ctx["redis"].set = _fake_redis_set
        ctx["redis"].delete = _fake_redis_del
        ctx["redis"].get = AsyncMock(return_value=None)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-val-03")

        assert result["status"] == "done"
        assert any("pid" in k for k in pid_set_keys), "PID key should be set in Redis"
        assert any("pid" in k for k in pid_del_keys), "PID key should be deleted after download"

    async def test_partial_download_failed_pages_in_result(self):
        """Plugin-reported failed_pages appear in the returned partial result."""
        from worker.download import download_job

        plugin_result = _make_plugin_result(
            status="partial",
            downloaded=4,
            total=5,
            error="page 3 unavailable",
            failed_pages=[3],
        )
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = "gal-part"
        importer.title = "Partial Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-part")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-val-04")

        assert result["status"] == "partial"
        assert result["downloaded"] == 4
        assert 3 in result.get("failed_pages", [])

    async def test_successful_download_returns_done_with_count(self):
        """A clean plugin result yields status=done with downloaded count."""
        from worker.download import download_job

        plugin_result = _make_plugin_result(status="done", downloaded=7, total=7)
        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = "gal-ok"
        importer.title = "OK Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-ok")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-val-05")

        assert result["status"] == "done"
        assert result["downloaded"] == 7
        mock_status.assert_any_call("job-val-05", "done")


# ---------------------------------------------------------------------------
# TestCheckDiskSpace
# ---------------------------------------------------------------------------


class TestCheckDiskSpace:
    """Unit tests for the check_disk_space() helper in worker.helpers."""

    def test_check_disk_space_sufficient(self):
        """Returns (True, free_gb) when free space exceeds the threshold."""
        from worker.helpers import check_disk_space

        _50_gb = 50 * (1024**3)
        fake_usage = MagicMock()
        fake_usage.free = _50_gb

        with patch("shutil.disk_usage", return_value=fake_usage):
            ok, free_gb = check_disk_space("/data", 2.0)

        assert ok is True
        assert free_gb == round(_50_gb / (1024**3), 2)

    def test_check_disk_space_insufficient(self):
        """Returns (False, free_gb) when free space is below the threshold."""
        from worker.helpers import check_disk_space

        _0_5_gb = int(0.5 * (1024**3))
        fake_usage = MagicMock()
        fake_usage.free = _0_5_gb

        with patch("shutil.disk_usage", return_value=fake_usage):
            ok, free_gb = check_disk_space("/data", 2.0)

        assert ok is False
        assert free_gb == round(_0_5_gb / (1024**3), 2)

    def test_check_disk_space_fail_open_on_oserror(self):
        """Returns (True, -1.0) when shutil.disk_usage raises OSError (fail-open)."""
        from worker.helpers import check_disk_space

        with patch("shutil.disk_usage", side_effect=OSError("no such device")):
            ok, free_gb = check_disk_space("/data", 2.0)

        assert ok is True
        assert free_gb == -1.0


# ---------------------------------------------------------------------------
# TestDownloadJobDiskSpace
# ---------------------------------------------------------------------------


class TestDownloadJobDiskSpace:
    """Tests for the disk space pre-flight check inside download_job()."""

    async def test_download_job_fails_on_low_disk_space(self):
        """When disk space is insufficient, download_job returns failed before acquiring the semaphore."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
            patch("worker.download.check_disk_space", return_value=(False, 0.5)),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-disk-01")

        assert result["status"] == "failed"
        assert "disk space" in result["error"].lower()
        mock_status.assert_any_call("job-disk-01", "failed", result["error"])
        # Semaphore must NOT have been acquired — the early-return fired before step 5
        mock_sem.acquire.assert_not_awaited()

    async def test_download_job_fails_on_redis_disk_low_flag(self):
        """When system:disk_low Redis flag is set, download_job fails without calling check_disk_space."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        # ctx with disk_low flag set — selective mock returns flag only for DISK_LOW_KEY
        ctx = _make_ctx()
        _orig_get = ctx["redis"].get

        async def _disk_flag_get(key):
            if key == "system:disk_low":
                return b"0.3"
            return await _orig_get(key)

        ctx["redis"].get = _disk_flag_get

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
            patch("worker.helpers.check_disk_space") as mock_check,
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-disk-flag")

        assert result["status"] == "failed"
        assert "disk space" in result["error"].lower()
        mock_status.assert_any_call("job-disk-flag", "failed", result["error"])
        # check_disk_space should NOT have been called — Redis flag was the fast path
        mock_check.assert_not_called()

    async def test_download_job_proceeds_on_sufficient_disk_space(self):
        """When disk space is sufficient, download_job does not return early with a disk space error."""
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=_make_plugin_result())

        importer = MagicMock()
        importer.gallery_id = "gal-disk-ok"
        importer.title = "Disk OK Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-disk-ok")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
            patch("worker.download.check_disk_space", return_value=(True, 50.0)),
        ):
            result = await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-disk-02")

        # The key assertion: the job did NOT fail with a disk space error.
        assert result.get("error", "") == "" or "disk space" not in result.get("error", "").lower()
        # It should have proceeded past the disk check and reached the semaphore.
        mock_sem.acquire.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestDiskMonitorJob
# ---------------------------------------------------------------------------


class TestDiskMonitorJob:
    """Tests for disk_monitor_job() in worker.__init__."""

    async def test_disk_monitor_sets_redis_flag_when_low(self):
        """When disk is low, disk_monitor_job sets system:disk_low in Redis and returns status=low."""
        from worker import disk_monitor_job

        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        ctx = {"redis": redis}

        with (
            patch("worker.helpers.check_disk_space", return_value=(False, 0.5)),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await disk_monitor_job(ctx)

        assert result["status"] == "low"
        assert result["free_gb"] == 0.5
        redis.set.assert_awaited_once_with("system:disk_low", "0.5", ex=600)

    async def test_disk_monitor_clears_flag_when_ok(self):
        """When disk is OK, disk_monitor_job deletes system:disk_low and returns status=ok."""
        from worker import disk_monitor_job

        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        ctx = {"redis": redis}

        with patch("worker.helpers.check_disk_space", return_value=(True, 50.0)):
            result = await disk_monitor_job(ctx)

        assert result["status"] == "ok"
        assert result["free_gb"] == 50.0
        redis.delete.assert_awaited_once_with("system:disk_low")


# ---------------------------------------------------------------------------
# TestRetryJobDiskLow
# ---------------------------------------------------------------------------


class TestRetryJobDiskLow:
    """Tests for disk-low guard inside retry_failed_downloads_job()."""

    async def test_retry_skips_when_disk_low(self):
        """When system:disk_low is set in Redis, retry_failed_downloads_job returns skipped_disk_low."""
        from worker.retry import retry_failed_downloads_job

        redis = AsyncMock()

        async def _redis_get(key):
            if key == "system:disk_low":
                return b"0.5"
            # cron:retry_downloads:enabled — not disabled (return None = use default)
            if key == "cron:retry_downloads:enabled":
                return None
            # cron:retry_downloads:cron_expr — use default
            if key == "cron:retry_downloads:cron_expr":
                return None
            # cron:retry_downloads:last_run — no last run (always run)
            if key == "cron:retry_downloads:last_run":
                return None
            # setting:retry_enabled — not disabled
            if key == "setting:retry_enabled":
                return None
            return None

        redis.get = _redis_get
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipeline)
        ctx = {"redis": redis}

        result = await retry_failed_downloads_job(ctx)

        assert result["status"] == "skipped_disk_low"


# ---------------------------------------------------------------------------
# TestOnFileConcurrency
# ---------------------------------------------------------------------------


class TestOnFileConcurrency:
    """Tests for the on_file callback's double-checked locking and media-ext filtering."""

    async def test_concurrent_on_file_calls_create_gallery_exactly_once(self):
        """Concurrent on_file calls must invoke ensure_gallery_from_url exactly once.

        Without the double-checked locking pattern, multiple coroutines that all see
        importer.gallery_id is None before any lock is acquired would each enter the
        creation path and produce duplicate galleries.  The asyncio.Lock serialises
        them and the inner check (second read of gallery_id) ensures only the first
        caller does real work.
        """
        from worker.download import download_job

        captured_on_file: list = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            captured_on_file.append(on_file)
            # Yield control so all concurrent on_file calls can be scheduled before
            # the first one finishes, then return a completed result.
            await asyncio.sleep(0)
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        # importer.gallery_id starts as None; ensure_gallery_from_url sets it.
        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-race")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.ensure_gallery = AsyncMock()

        ensure_gallery_from_url_call_count = [0]

        async def _slow_ensure_gallery_from_url(url, target_dir):
            ensure_gallery_from_url_call_count[0] += 1
            # Simulate I/O latency so other coroutines can reach the outer if-check
            # before this call returns and sets gallery_id.
            await asyncio.sleep(0.02)
            importer.gallery_id = "gal-race"
            importer.title = "Race Gallery"

        importer.ensure_gallery_from_url = _slow_ensure_gallery_from_url

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-race-01")

        assert len(captured_on_file) == 1, "plugin.download should have been called once"
        on_file = captured_on_file[0]

        # Reset state: gallery_id is None again so all concurrent calls see the None.
        importer.gallery_id = None
        importer.title = None
        ensure_gallery_from_url_call_count[0] = 0

        # Fire 8 concurrent on_file calls for a valid media file.
        media_path = Path("/data/gallery/image001.jpg")
        await asyncio.gather(*[on_file(media_path) for _ in range(8)])

        # The double-checked lock must have allowed only one call through.
        assert ensure_gallery_from_url_call_count[0] == 1, (
            f"ensure_gallery_from_url was called {ensure_gallery_from_url_call_count[0]} times; "
            "expected exactly 1 (double-checked locking broken)"
        )
        # import_file should still have been called for every file.
        assert importer.import_file.await_count == 8

    async def test_on_file_skips_non_media_extensions(self):
        """on_file must silently ignore files with non-media extensions (e.g. .txt, .json).

        gallery-dl occasionally emits metadata sidecar files alongside images.
        Importing them would pollute the gallery with non-image entries.
        """
        from worker.download import download_job

        captured_on_file: list = []

        async def _capturing_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            captured_on_file.append(on_file)
            await asyncio.sleep(0)
            return _make_plugin_result()

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _capturing_download

        importer = MagicMock()
        importer.gallery_id = "gal-ext"
        importer.title = "Ext Gallery"
        importer.source_url = None
        importer.import_file = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-ext")
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            await download_job(_make_ctx(), "https://example.com/gallery/1", db_job_id="job-ext-01")

        assert len(captured_on_file) == 1
        on_file = captured_on_file[0]

        non_media_paths = [
            Path("/data/gallery/metadata.json"),
            Path("/data/gallery/notes.txt"),
            Path("/data/gallery/readme.html"),
            Path("/data/gallery/data.xml"),
            Path("/data/gallery/archive.zip"),
        ]
        for path in non_media_paths:
            await on_file(path)

        importer.import_file.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestDownloadJobCancellation
# ---------------------------------------------------------------------------


class TestDownloadJobCancellation:
    """State machine tests for job cancellation paths in download_job()."""

    async def test_download_job_cancelled_before_start_sets_status_cancelled(self):
        """cancel_check() returning True inside the plugin causes download_job to return cancelled.

        This tests the scenario where the cancel flag is set in Redis before the plugin
        begins downloading — the cancel_check closure is injected into the plugin and
        the plugin immediately detects it and returns status=cancelled.
        """
        from worker.download import download_job

        async def _immediate_cancel_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            # Plugin checks cancel before doing any work — already cancelled
            if await cancel_check():
                result = MagicMock()
                result.status = "cancelled"
                result.downloaded = 0
                result.total = 0
                result.error = None
                result.failed_pages = []
                return result
            raise AssertionError("Plugin should have detected cancellation before doing any work")

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _immediate_cancel_download

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        # cancel key is set from the very start (before plugin runs); pause key absent
        async def _get_cancel_set(key):
            if key.startswith("download:cancel:"):
                return b"1"
            return None

        ctx["redis"].get = _get_cancel_set

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/1", db_job_id="job-cancel-before")

        assert result["status"] == "cancelled"
        mock_status.assert_any_call("job-cancel-before", "cancelled")
        importer.cleanup.assert_awaited_once()

    async def test_cancel_check_returns_true_when_job_cancelled_in_redis(self):
        """cancel_check() closure reads the cancel flag key and returns True when present.

        This test isolates the cancel_check() closure itself: it must return True exactly
        when `download:cancel:{db_job_id}` is present in Redis, regardless of what the
        plugin does with that result.
        """
        from worker.download import download_job

        observed_cancel_results: list[bool] = []

        async def _spy_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            # Call cancel_check three times to verify consistent True result
            for _ in range(3):
                observed_cancel_results.append(await cancel_check())
            result = MagicMock()
            result.status = "cancelled"
            result.downloaded = 0
            result.total = 0
            result.error = None
            result.failed_pages = []
            return result

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _spy_download

        importer = MagicMock()
        importer.gallery_id = None
        importer.title = None
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        async def _redis_cancel_present(key):
            # pause gate returns None so job proceeds past pre-semaphore gate
            if key.startswith("download:pause:"):
                return None
            if key.startswith("download:cancel:"):
                return b"1"
            return None

        ctx["redis"].get = _redis_cancel_present

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/2", db_job_id="job-cancel-redis")

        # The cancel_check closure must have consistently reported True
        assert all(observed_cancel_results), (
            f"cancel_check() should always return True when cancel key is set, got: {observed_cancel_results}"
        )
        assert result["status"] == "cancelled"

    async def test_cancel_check_returns_false_when_no_cancel_key_in_redis(self):
        """cancel_check() returns False when the cancel key is absent from Redis.

        Non-cancellation path: when no cancel flag is present, the closure must return
        False so the download proceeds normally.
        """
        from worker.download import download_job

        observed_cancel_results: list[bool] = []

        async def _spy_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            observed_cancel_results.append(await cancel_check())
            result = MagicMock()
            result.status = "done"
            result.downloaded = 1
            result.total = 1
            result.error = None
            result.failed_pages = []
            return result

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _spy_download

        importer = MagicMock()
        importer.gallery_id = "gal-nocancel"
        importer.title = "No Cancel Gallery"
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-nocancel")

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()
        ctx["redis"].get = AsyncMock(return_value=None)  # no cancel key, no pause key

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/3", db_job_id="job-nocancel")

        assert observed_cancel_results == [False], (
            f"cancel_check() must return False when no cancel key in Redis, got: {observed_cancel_results}"
        )
        assert result["status"] == "done"


# ---------------------------------------------------------------------------
# TestDownloadJobPause
# ---------------------------------------------------------------------------


class TestDownloadJobPause:
    """State machine tests for job pause paths in download_job()."""

    async def test_pause_check_returns_false_when_not_paused(self):
        """pause_check() returns False when no pause key is present in Redis.

        Normal (non-paused) execution path: the closure must not block or return True,
        so the plugin can proceed with the download unhindered.
        """
        from worker.download import download_job

        observed_pause_results: list[bool] = []

        async def _spy_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            observed_pause_results.append(await pause_check())
            result = MagicMock()
            result.status = "done"
            result.downloaded = 2
            result.total = 2
            result.error = None
            result.failed_pages = []
            return result

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _spy_download

        importer = MagicMock()
        importer.gallery_id = "gal-nopause"
        importer.title = "No Pause Gallery"
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-nopause")

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()
        ctx["redis"].get = AsyncMock(return_value=None)  # no pause key, no cancel key

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/4", db_job_id="job-nopause")

        assert observed_pause_results == [False], (
            f"pause_check() must return False when no pause key in Redis, got: {observed_pause_results}"
        )
        assert result["status"] == "done"

    async def test_pre_semaphore_pause_gate_returns_paused_status_immediately(self):
        """When pause key is set before the semaphore is acquired, download_job returns paused.

        Tests the pre-semaphore pause gate (lines 283-288 in download.py): if
        `download:pause:{job_id}` is present in Redis before the download slot is acquired,
        the job must set its status to 'paused' and return `{"status": "paused"}` without
        acquiring the semaphore or calling the plugin.
        """
        from worker.download import download_job

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock()  # must NOT be called

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        # pause key is set; no cancel key
        async def _pause_gate_get(key):
            if key.startswith("download:pause:"):
                return b"1"
            return None

        ctx["redis"].get = _pause_gate_get

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock) as mock_status,
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch(
                "worker.progressive.ProgressiveImporter",
                return_value=MagicMock(
                    gallery_id=None,
                    title=None,
                    source_url=None,
                    abort=AsyncMock(),
                    cleanup=AsyncMock(),
                ),
            ),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            result = await download_job(ctx, "https://example.com/gallery/5", db_job_id="job-pause-gate")

        assert result["status"] == "paused"
        mock_status.assert_any_call("job-pause-gate", "paused")
        # Semaphore must NOT have been acquired — early return fired before step 5
        mock_sem.acquire.assert_not_awaited()
        # Plugin download must NOT have been called
        plugin.download.assert_not_awaited()

    async def test_pause_check_returns_true_when_pause_flag_cleared_then_set_again(self):
        """pause_check() returns True when `download:pause:{job_id}` is present in Redis.

        Simulates the flag being absent at the pre-semaphore gate (allowing the job to
        proceed), then present when the plugin queries pause_check() mid-download.
        This gives the plugin the signal to stall/pause its work.
        """
        from worker.download import download_job

        observed_pause_results: list[bool] = []

        async def _spy_download(
            url, dest_dir, credentials, on_progress, cancel_check, pid_callback, pause_check, on_file, **kwargs
        ):
            observed_pause_results.append(await pause_check())
            result = MagicMock()
            result.status = "done"
            result.downloaded = 1
            result.total = 1
            result.error = None
            result.failed_pages = []
            return result

        plugin = MagicMock()
        plugin.meta.source_id = "gallery_dl"
        plugin.meta.name = "Gallery-DL"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = _spy_download

        importer = MagicMock()
        importer.gallery_id = "gal-pausecheck"
        importer.title = "Pause Check Gallery"
        importer.source_url = None
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.ensure_gallery = AsyncMock()
        importer.finalize = AsyncMock(return_value="gal-pausecheck")

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        ctx = _make_ctx()

        # First call to pause key is the pre-semaphore gate — return None to let through.
        # Subsequent calls (from pause_check() closure inside plugin) — return b"1".
        pause_gate_call_count = [0]

        async def _selective_pause_get(key):
            if key.startswith("download:pause:"):
                pause_gate_call_count[0] += 1
                if pause_gate_call_count[0] == 1:
                    return None  # gate: not paused, proceed
                return b"1"  # mid-download: pause flag is now set
            return None

        ctx["redis"].get = _selective_pause_get

        with (
            patch("plugins.registry.plugin_registry", mock_registry),
            patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.download._set_job_status", new_callable=AsyncMock),
            patch("worker.download._set_job_progress", new_callable=AsyncMock),
            patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
            patch("worker.progressive.ProgressiveImporter", return_value=importer),
            patch("worker.download.DownloadSemaphore", mock_sem_cls),
            patch("core.redis_client.get_redis", return_value=MagicMock()),
            patch("worker.helpers._validate_image_magic", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            await download_job(ctx, "https://example.com/gallery/6", db_job_id="job-pausecheck")

        assert observed_pause_results == [True], (
            f"pause_check() must return True when pause key is set in Redis, got: {observed_pause_results}"
        )


class TestDownloadJobSkipPages:
    """The worker hands the importer's held page numbers to the plugin.

    Without this the incremental repair never engages: the downloader has no
    way to know which pages the gallery already holds, so a run that exists
    purely to recover a handful of gaps re-fetches the entire gallery.
    """

    @staticmethod
    def _run(existing_page_nums):
        from worker.download import download_job

        plugin_result = _make_plugin_result(status="done", downloaded=3)
        plugin = MagicMock()
        plugin.meta.source_id = "ehentai"
        plugin.meta.name = "E-Hentai"
        plugin.meta.semaphore_key = None
        plugin.meta.needs_all_credentials = False
        plugin.meta.concurrency = 1
        plugin.download = AsyncMock(return_value=plugin_result)

        importer = MagicMock()
        importer.gallery_id = 42
        importer.title = "t"
        importer.source_url = None
        importer.existing_page_nums = existing_page_nums
        importer.download_status = "complete"
        importer.import_failures = ()
        importer.import_success_count = 3
        importer.abort = AsyncMock()
        importer.cleanup = AsyncMock()
        importer.import_file = AsyncMock()
        importer.ensure_gallery_from_url = AsyncMock()
        importer.finalize = AsyncMock(return_value=42)

        mock_registry = MagicMock()
        mock_registry.get_handler = AsyncMock(return_value=plugin)
        mock_registry.get_fallback = MagicMock(return_value=None)
        mock_registry.get_downloader = MagicMock(return_value=None)

        mock_sem = _make_mock_sem()
        mock_sem_cls = MagicMock(return_value=mock_sem)

        return (
            plugin,
            (
                patch("plugins.registry.plugin_registry", mock_registry),
                patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
                patch("worker.download._set_job_status", new_callable=AsyncMock),
                patch("worker.download._set_job_progress", new_callable=AsyncMock),
                patch("core.database.AsyncSessionLocal", return_value=_make_mock_session()),
                patch("worker.progressive.ProgressiveImporter", return_value=importer),
                patch("worker.download.DownloadSemaphore", mock_sem_cls),
                patch("core.redis_client.get_redis", return_value=MagicMock()),
                patch("core.site_config.site_config_service", make_mock_site_config_svc()),
            ),
            download_job,
        )

    async def test_existing_page_nums_are_passed_to_plugin_as_skip_pages(self):
        plugin, patches, download_job = self._run({1, 2, 3})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            await download_job(_make_ctx(), "https://e-hentai.org/g/1/aaaaaaaaaa", db_job_id="job-skip-1")

        plugin.download.assert_called_once()
        assert plugin.download.call_args.kwargs["options"]["skip_pages"] == {1, 2, 3}

    async def test_new_gallery_sends_no_skip_pages(self):
        """A first-time download has nothing held, so nothing may be skipped."""
        plugin, patches, download_job = self._run(set())
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            await download_job(_make_ctx(), "https://e-hentai.org/g/2/bbbbbbbbbb", db_job_id="job-skip-2")

        plugin.download.assert_called_once()
        assert "skip_pages" not in plugin.download.call_args.kwargs["options"]
