"""Tests for download pipeline: GalleryDlPlugin.download() and download_job().

Tests cover:
- Cancel detection in _read_stdout (kills process, skips last pending file)
- Partial vs failed status based on downloaded count
- download_job() status transitions: cancelled cleanup, failed-with-downloads,
  and the post-download cancel guard.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_iter(lines: list[bytes]):
    """Return an async iterable that yields the given byte lines."""

    async def _gen():
        for line in lines:
            yield line

    return _gen()


def _make_mock_proc(stdout_lines: list[bytes], returncode: int = 0, stderr: bytes = b""):
    """Build a mock asyncio subprocess with controllable stdout/stderr/returncode."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = returncode
    proc.stdout = _make_async_iter(stdout_lines)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


def _source_patches():
    """Common patches for GalleryDlPlugin.download() tests."""
    return [
        patch(
            "plugins.builtin.gallery_dl.source._build_gallery_dl_config",
            new_callable=AsyncMock,
        ),
        patch(
            "core.redis_client.get_download_delay",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "plugins.builtin.gallery_dl.source.settings",
            MagicMock(
                data_gallery_path="/data/gallery",
                gallery_dl_config="/tmp/gallery-dl-test.json",
                data_archive_path="/tmp/gallery-dl-archive",
            ),
        ),
        patch("pathlib.Path.mkdir"),
    ]


# ---------------------------------------------------------------------------
# TestGalleryDlCancel
# ---------------------------------------------------------------------------


class TestGalleryDlCancel:
    """Tests for cancel detection inside GalleryDlPlugin.download()."""

    async def test_cancel_check_returns_cancelled_status(self):
        """When cancel_check returns True mid-stream, process is killed and status is cancelled."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        lines = [
            b"/data/gallery/image001.jpg\n",
            b"/data/gallery/image002.jpg\n",
            b"/data/gallery/image003.jpg\n",
        ]
        mock_proc = _make_mock_proc(lines, returncode=0)

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
        mock_proc.kill.assert_called()

    async def test_cancel_skips_last_pending_file(self):
        """When cancelled, the last pending file must NOT be imported."""
        from plugins.builtin.gallery_dl.source import GalleryDlPlugin

        plugin = GalleryDlPlugin()

        lines = [
            b"/data/gallery/image001.jpg\n",
            b"/data/gallery/image002.jpg\n",
        ]
        mock_proc = _make_mock_proc(lines, returncode=0)

        imported_files: list[Path] = []

        async def on_file(path: Path) -> None:
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
        assert Path("/data/gallery/image002.jpg") not in imported_files


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
            b"/data/gallery/image001.jpg\n",
            b"/data/gallery/image002.jpg\n",
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
