"""Inactivity watchdog: a slow download of one large file is not inactivity.

gallery-dl prints nothing while a file is in flight. Subscription #48 died twice
on the same 36 MB video: at ~40 KB/s it takes ~16 minutes, the 600 s watchdog
saw no stdout/stderr and killed the process ("No output for 600s").
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.builtin.gallery_dl import source
from plugins.builtin.gallery_dl.source import _DownloadState, _inactivity_watchdog

_TIMEOUT_S = 0.3
_POLL_S = 0.05


def _state() -> _DownloadState:
    return _DownloadState(last_activity=asyncio.get_running_loop().time())


@pytest.mark.asyncio
async def test_growing_part_file_without_any_output_does_not_trip_the_inactivity_timeout(tmp_path):
    part = tmp_path / "2071444212495896610_1.mp4.part"
    part.write_bytes(b"x")
    state = _state()

    async def _keep_downloading():
        while True:
            await asyncio.sleep(_POLL_S)
            with part.open("ab") as fp:
                fp.write(b"x" * 1024)

    with patch.object(source, "_terminate_process_tree", new_callable=AsyncMock) as terminate:
        writer = asyncio.create_task(_keep_downloading())
        watchdog = asyncio.create_task(
            _inactivity_watchdog(state, _TIMEOUT_S, MagicMock(), watch_dir=tmp_path, poll_s=_POLL_S)
        )
        await asyncio.sleep(_TIMEOUT_S * 3)
        still_running = not watchdog.done()
        writer.cancel()
        watchdog.cancel()

    assert still_running
    terminate.assert_not_awaited()


@pytest.mark.asyncio
async def test_part_file_that_stopped_growing_still_trips_the_inactivity_timeout(tmp_path):
    (tmp_path / "stalled.mp4.part").write_bytes(b"x" * 4096)
    state = _state()

    with patch.object(source, "_terminate_process_tree", new_callable=AsyncMock) as terminate:
        result = await asyncio.wait_for(
            _inactivity_watchdog(state, _TIMEOUT_S, MagicMock(), watch_dir=tmp_path, poll_s=_POLL_S), timeout=5
        )

    assert result == "inactivity_timeout"
    terminate.assert_awaited_once()


@pytest.mark.asyncio
async def test_finished_files_in_the_staging_dir_do_not_count_as_activity(tmp_path):
    (tmp_path / "done_1.jpg").write_bytes(b"x" * 4096)
    (tmp_path / "done_1.jpg.json").write_text("{}")
    state = _state()

    with patch.object(source, "_terminate_process_tree", new_callable=AsyncMock):
        result = await asyncio.wait_for(
            _inactivity_watchdog(state, _TIMEOUT_S, MagicMock(), watch_dir=tmp_path, poll_s=_POLL_S), timeout=5
        )

    assert result == "inactivity_timeout"


@pytest.mark.asyncio
async def test_missing_staging_dir_falls_back_to_output_only_inactivity(tmp_path):
    state = _state()

    with patch.object(source, "_terminate_process_tree", new_callable=AsyncMock):
        result = await asyncio.wait_for(
            _inactivity_watchdog(state, _TIMEOUT_S, MagicMock(), watch_dir=tmp_path / "gone", poll_s=_POLL_S),
            timeout=5,
        )

    assert result == "inactivity_timeout"
