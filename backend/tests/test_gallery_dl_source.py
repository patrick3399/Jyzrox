"""
Tests for plugins/builtin/gallery_dl/source.py — GalleryDlPlugin.

Mocks asyncio.create_subprocess_exec to avoid real gallery-dl subprocess calls.
Tests cover: download happy path, error handling, cancellation, timeout,
partial success, can_handle, resolve_output_dir, parse_metadata.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.site_config import DownloadParams
from tests.helpers import make_mock_site_config_svc


@pytest.fixture(autouse=True)
def mock_site_config_for_source():
    """Mock SiteConfigService, Redis, and adaptive engine for all source.py download tests."""
    svc = make_mock_site_config_svc()
    mock_pipeline = MagicMock()
    mock_pipeline.get = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    mock_redis.get = AsyncMock(return_value=None)

    from core.adaptive import AdaptiveState

    mock_adaptive = MagicMock()
    mock_adaptive.get_state = AsyncMock(return_value=AdaptiveState())

    with (
        patch("core.site_config.site_config_service", svc),
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.adaptive.adaptive_engine", mock_adaptive),
    ):
        yield svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_process(
    stdout_lines: list[bytes],
    returncode: int = 0,
    stderr: bytes = b"",
    block_wait: bool = False,
):
    """Build a mock asyncio.subprocess.Process.

    Args:
        block_wait: if True, proc.wait() blocks until kill() is called.
                    Use this for cancel/pause tests.
    """
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = returncode

    # stdout: async iterator over lines
    async def _async_iter_lines():
        for line in stdout_lines:
            yield line

    proc.stdout = _async_iter_lines()

    # stderr: async iterator over lines (split from bytes)
    stderr_lines = [l + b"\n" for l in stderr.split(b"\n") if l] if stderr else []

    async def _async_iter_stderr():
        for line in stderr_lines:
            yield line

    proc.stderr = _async_iter_stderr()

    if block_wait:
        _kill_event = asyncio.Event()

        def _do_kill():
            proc.returncode = -9
            _kill_event.set()

        proc.kill = MagicMock(side_effect=_do_kill)

        async def _blocking_wait():
            await _kill_event.wait()
            return proc.returncode

        proc.wait = _blocking_wait
    else:
        proc.wait = AsyncMock(return_value=returncode)
        proc.kill = MagicMock()

    return proc


async def _noop(*args, **kwargs):
    pass


# ---------------------------------------------------------------------------
# GalleryDlPlugin.can_handle
# ---------------------------------------------------------------------------


class TestGalleryDlCanHandle:
    """GalleryDlPlugin.can_handle — always returns True (universal fallback)."""

    async def test_can_handle_returns_true_for_any_url(self):
        """GalleryDlPlugin acts as a universal fallback and handles all URLs."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        assert await plugin.can_handle("https://example.com/gallery/1") is True
        assert await plugin.can_handle("https://twitter.com/user/status/123") is True
        assert await plugin.can_handle("https://danbooru.donmai.us/posts/1") is True

    async def test_resolve_metadata_returns_none(self):
        """GalleryDlPlugin.resolve_metadata always returns None (metadata discovered during download)."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = await plugin.resolve_metadata("https://example.com/x", credentials=None)
        assert result is None

    def test_resolve_output_dir_returns_base_path(self, tmp_path):
        """resolve_output_dir ignores the URL and returns the base_path directly."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        out = plugin.resolve_output_dir("https://example.com/anything", tmp_path)
        assert out == tmp_path

    def test_requires_credentials_returns_false(self):
        """gallery-dl doesn't strictly require credentials."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        assert plugin.requires_credentials() is False


# ---------------------------------------------------------------------------
# GalleryDlPlugin.download — happy path
# ---------------------------------------------------------------------------


class TestGalleryDlDownloadHappyPath:
    """download() — subprocess succeeds with downloaded files."""

    async def test_download_success_returns_done_status(self, tmp_path):
        """When gallery-dl exits 0 with JYZROX_FILE lines, status=done is returned."""
        lines = [
            b"JYZROX_FILE\t/data/gallery/test/img001.jpg\tabc123\n",
            b"JYZROX_FILE\t/data/gallery/test/img002.jpg\tdef456\n",
        ]
        proc = _make_fake_process(lines, returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/gallery/1",
                dest_dir=tmp_path,
                credentials={},
            )

        assert result.status == "done"
        assert result.downloaded == 2

    async def test_download_calls_pid_callback(self, tmp_path):
        """When pid_callback is provided, it should be called with the process PID."""
        proc = _make_fake_process([b"JYZROX_FILE\t/data/x.jpg\tabc123\n"], returncode=0)
        pid_received = []

        async def _pid_cb(pid: int):
            pid_received.append(pid)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            await plugin.download(
                url="https://example.com/gallery/1",
                dest_dir=tmp_path,
                credentials={},
                pid_callback=_pid_cb,
            )

        assert pid_received == [12345]

    async def test_download_calls_on_progress(self, tmp_path):
        """on_progress callback should be invoked when progress threshold is reached."""
        # Generate enough lines to trigger progress (every 5 or every 10s)
        lines = [f"JYZROX_FILE\t/data/img{i:03d}.jpg\tabc{i:03d}\n".encode() for i in range(10)]
        proc = _make_fake_process(lines, returncode=0)
        progress_calls = []

        async def _on_progress(downloaded, total):
            progress_calls.append((downloaded, total))

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
                on_progress=_on_progress,
            )

        assert result.downloaded == 10
        assert len(progress_calls) >= 1


# ---------------------------------------------------------------------------
# GalleryDlPlugin.download — error paths
# ---------------------------------------------------------------------------


class TestGalleryDlDownloadErrors:
    """download() — error handling."""

    async def test_oserror_starting_process_returns_failed(self, tmp_path):
        """If gallery-dl binary is not found, OSError → status=failed."""
        with (
            patch("asyncio.create_subprocess_exec", side_effect=OSError("No such file")),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/fail",
                dest_dir=tmp_path,
                credentials={},
            )

        assert result.status == "failed"
        assert "gallery-dl" in result.error.lower()

    async def test_nonzero_exit_no_files_returns_failed(self, tmp_path):
        """Non-zero exit with no files downloaded → status=failed."""
        proc = _make_fake_process([], returncode=1, stderr=b"Error: login required\n")

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
            )

        assert result.status == "failed"
        assert result.downloaded == 0
        assert result.error  # some error text from stderr

    async def test_nonzero_exit_with_files_returns_partial(self, tmp_path):
        """Non-zero exit after some files were downloaded → status=partial."""
        lines = [b"JYZROX_FILE\t/data/img001.jpg\tabc123\n", b"JYZROX_FILE\t/data/img002.jpg\tdef456\n"]
        proc = _make_fake_process(lines, returncode=1, stderr=b"Error mid-way\n")

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
            )

        assert result.status == "partial"
        assert result.downloaded == 2

    async def test_cancel_check_true_returns_cancelled(self, tmp_path):
        """When cancel_check immediately returns True, status=cancelled."""
        # Provide one line so the loop runs at least once
        lines = [b"JYZROX_FILE\t/data/img001.jpg\tabc123\n"]
        proc = _make_fake_process(lines, returncode=0, block_wait=True)

        async def _always_cancel():
            return True

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
                cancel_check=_always_cancel,
            )

        assert result.status == "cancelled"

    async def test_nondefault_retries_appended_to_cmd(self, tmp_path, mock_site_config_for_source):
        """When SiteConfigService returns non-default retries, --retries flag is added."""
        proc = _make_fake_process([], returncode=0)
        captured_cmd = []

        async def _capture_exec(*cmd, **kwargs):
            captured_cmd.extend(cmd)
            return proc

        mock_site_config_for_source.get_effective_download_params = AsyncMock(
            return_value=DownloadParams(retries=8, http_timeout=60)
        )

        with (
            patch("asyncio.create_subprocess_exec", side_effect=_capture_exec),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
            )

        assert "--retries" in captured_cmd
        idx = captured_cmd.index("--retries")
        assert captured_cmd[idx + 1] == "8"
        assert "--http-timeout" in captured_cmd
        idx2 = captured_cmd.index("--http-timeout")
        assert captured_cmd[idx2 + 1] == "60"


# ---------------------------------------------------------------------------
# GalleryDlPlugin.parse_metadata
# ---------------------------------------------------------------------------


class TestGalleryDlParseMetadata:
    """parse_metadata() — reads the first *.json file in dest_dir."""

    def test_parse_metadata_returns_none_when_no_json(self, tmp_path):
        """No JSON files in dest_dir → parse_metadata returns None."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = plugin.parse_metadata(tmp_path)
        assert result is None

    def test_parse_metadata_returns_gallery_metadata_from_json(self, tmp_path):
        """A valid *.json file is read and converted to GalleryMetadata."""
        meta = {
            "category": "danbooru",
            "id": 9999,
            "title": "Test Gallery",
            "tags": ["blue_hair", "solo"],
            "count": 5,
            "uploader": "artist_x",
        }
        (tmp_path / "meta.json").write_text(json.dumps(meta))

        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = plugin.parse_metadata(tmp_path)

        assert result is not None
        assert result.title == "Test Gallery"
        assert result.source == "danbooru"
        assert result.pages == 5
        assert "blue_hair" in result.tags

    def test_parse_metadata_handles_invalid_json_gracefully(self, tmp_path):
        """A corrupted JSON file should not raise; returns None."""
        (tmp_path / "bad.json").write_text("not valid json{{{{")

        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = plugin.parse_metadata(tmp_path)
        assert result is None

    def test_parse_metadata_appends_rating_tag(self, tmp_path):
        """When raw JSON has a 'rating' field, it is appended as 'rating:<value>' to tags."""
        meta = {
            "category": "danbooru",
            "id": 123,
            "title": "Rated Art",
            "tags": ["original"],
            "rating": "safe",
            "count": 1,
        }
        (tmp_path / "m.json").write_text(json.dumps(meta))

        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = plugin.parse_metadata(tmp_path)

        assert result is not None
        assert "rating:safe" in result.tags

    def test_parse_metadata_uses_description_as_title_fallback(self, tmp_path):
        """When 'title' is absent, 'description' is used as fallback title."""
        meta = {
            "category": "gallery_dl",
            "description": "A description-based title",
            "id": "456",
            "count": 2,
        }
        (tmp_path / "m.json").write_text(json.dumps(meta))

        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()
        result = plugin.parse_metadata(tmp_path)

        assert result is not None
        assert result.title == "A description-based title"


# ---------------------------------------------------------------------------
# TestConfigGeneration
# ---------------------------------------------------------------------------


class TestConfigGeneration:
    """Tests for _build_gallery_dl_config — config file generation logic."""

    async def test_subscription_mode_sets_skip_and_archive_mode(self, tmp_path):
        """subscription job_context should set skip=abort:10 and archive-mode=memory in extractor."""
        from unittest.mock import MagicMock, patch

        from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

        config_file = tmp_path / "gallery-dl.json"
        mock_settings = MagicMock()
        mock_settings.data_gallery_path = str(tmp_path / "gallery")
        mock_settings.gdl_archive_dsn = "postgresql://test/archive"
        mock_settings.gallery_dl_config = str(config_file)

        with patch("plugins.builtin.gallery_dl.source.settings", mock_settings):
            path = await _build_gallery_dl_config({}, job_context="subscription")

        config = json.loads(path.read_text())
        assert config["extractor"].get("skip") == "abort:10"
        assert config["extractor"].get("archive-mode") == "memory"

    async def test_manual_mode_does_not_set_skip(self, tmp_path):
        """Default (manual) job_context should NOT set skip or archive-mode in extractor config."""
        from unittest.mock import MagicMock, patch

        from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

        config_file = tmp_path / "gallery-dl.json"
        mock_settings = MagicMock()
        mock_settings.data_gallery_path = str(tmp_path / "gallery")
        mock_settings.gdl_archive_dsn = "postgresql://test/archive"
        mock_settings.gallery_dl_config = str(config_file)

        with patch("plugins.builtin.gallery_dl.source.settings", mock_settings):
            path = await _build_gallery_dl_config({}, job_context="manual")

        config = json.loads(path.read_text())
        assert "skip" not in config["extractor"]
        assert "archive-mode" not in config["extractor"]


# ---------------------------------------------------------------------------
# TestProcessLifecycle
# ---------------------------------------------------------------------------


class TestProcessLifecycle:
    """Tests for heartbeat loop, pause/cancel watcher, and skip counting."""

    async def test_heartbeat_loop_eviction_kills_process(self):
        """_heartbeat_loop returns 'evicted' and kills the process when heartbeat returns False."""
        from plugins.builtin.gallery_dl.source import _DownloadState, _heartbeat_loop

        state = _DownloadState()
        proc = MagicMock()
        proc.kill = MagicMock()

        async def lost_heartbeat():
            return False  # semaphore eviction immediately

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _heartbeat_loop(state, proc, lost_heartbeat, interval=0.01)

        assert result == "evicted"
        proc.kill.assert_called_once()
        assert state.cancelled is True

    async def test_pause_cancel_watcher_sends_sigstop_and_sigcont(self):
        """_pause_cancel_watcher sends SIGSTOP when paused and SIGCONT when resumed."""
        import signal

        from plugins.builtin.gallery_dl.source import _DownloadState, _pause_cancel_watcher

        state = _DownloadState()
        proc = MagicMock()
        proc.send_signal = MagicMock()
        proc.kill = MagicMock()

        # pause_check: True (pause), then False (unpause)
        pause_seq = [True, False]
        cancel_calls = 0

        async def pause_check():
            return pause_seq.pop(0) if pause_seq else False

        async def cancel_check():
            nonlocal cancel_calls
            cancel_calls += 1
            return cancel_calls > 4  # allow a few iterations before ending

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await _pause_cancel_watcher(state, proc, cancel_check, pause_check)

        # SIGSTOP sent during pause, SIGCONT sent on resume
        proc.send_signal.assert_any_call(signal.SIGSTOP)
        proc.send_signal.assert_any_call(signal.SIGCONT)

    async def test_skipped_files_counted_in_download_total(self, tmp_path):
        """JYZROX_SKIP lines should increment skipped_count and be included in result.total."""
        lines = [
            b"JYZROX_FILE\t/data/img001.jpg\tabc123\n",
            b"JYZROX_SKIP\n",
            b"JYZROX_SKIP\n",
        ]
        proc = _make_fake_process(lines, returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc),
            patch(
                "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
                new_callable=AsyncMock,
                return_value=Path("/tmp/test-gdl.json"),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            from plugins.builtin.gallery_dl.source import GalleryDlPlugin

            plugin = GalleryDlPlugin()
            result = await plugin.download(
                url="https://example.com/x",
                dest_dir=tmp_path,
                credentials={},
            )

        assert result.status == "done"
        assert result.downloaded == 1
        assert result.total == 3  # 1 downloaded + 2 skipped
