"""gallery-dl config per download mode, and the drain of stdout after the process exits."""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_gallery_dl_source import _make_fake_process, mock_site_config_for_source  # noqa: F401 (autouse fixture)

SHADOW = f"newsite__repair_{uuid.UUID(int=7).hex}"


async def _config(tmp_path, **kwargs) -> dict:
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    mock_settings = MagicMock()
    mock_settings.data_gallery_path = str(tmp_path / "gallery")
    mock_settings.gdl_archive_dsn = "postgresql://test/archive"
    mock_settings.gallery_dl_config = str(tmp_path / "gallery-dl.json")
    with patch("plugins.builtin.gallery_dl.source.settings", mock_settings):
        path = await _build_gallery_dl_config({}, **kwargs)
    return json.loads(path.read_text())["extractor"]


async def test_incremental_mode_sets_date_after_and_abort(tmp_path):
    ext = await _config(tmp_path, mode="subscription_incremental", last_completed_at=datetime(2026, 10, 10, 12, 0, 0))

    assert ext["skip"] == "abort:10"
    assert ext["date-after"] == "2026-10-09T12:00:00"  # one day before the boundary


@pytest.mark.parametrize(
    "mode",
    ["subscription_initial", "download", "repair"],
)
async def test_non_incremental_modes_never_set_date_after_or_abort(tmp_path, mode):
    """The mode decides, not the presence of a date: only an incremental run may stop at a boundary."""
    ext = await _config(tmp_path, mode=mode, last_completed_at=datetime(2026, 10, 10, 12, 0, 0))

    assert "skip" not in ext
    assert "date-after" not in ext


async def test_incremental_mode_without_a_boundary_fetches_everything(tmp_path):
    ext = await _config(tmp_path, mode="subscription_incremental", last_completed_at=None)

    assert "skip" not in ext and "date-after" not in ext


async def test_repair_mode_uses_shadow_archive_table(tmp_path):
    ext = await _config(tmp_path, mode="repair", archive_table=SHADOW)

    assert ext["archive-table"] == SHADOW
    assert "archive" in ext  # still the PostgreSQL archive, just an empty per-job table
    assert "skip" not in ext and "date-after" not in ext


async def test_repair_mode_without_a_shadow_runs_without_any_archive(tmp_path):
    """The pre-shadow forced re-scan: a missing shadow degrades to no archive, never to the real table."""
    ext = await _config(tmp_path, mode="repair", archive_table=None)

    assert "archive" not in ext and "archive-table" not in ext


@pytest.mark.parametrize("mode", ["download", "subscription_initial", "subscription_incremental"])
async def test_other_modes_never_point_at_a_repair_shadow(tmp_path, mode):
    ext = await _config(tmp_path, mode=mode, archive_table=SHADOW)

    assert "__repair_" not in str(ext.get("archive-table", ""))


async def test_legacy_force_full_scan_flag_builds_a_repair_config(tmp_path):
    ext = await _config(tmp_path, job_context="subscription", force_full_scan=True, archive_table=SHADOW)

    assert ext["archive-table"] == SHADOW


# ── reader drain ────────────────────────────────────────────────────────


async def _download_with_late_line(tmp_path, on_file):
    """gallery-dl exits at once, but its last JYZROX_FILE line is still in flight on the pipe."""
    proc = _make_fake_process([], returncode=0)

    async def _stdout():
        yield b"JYZROX_FILE\t/data/a.jpg\taaa\n"
        await asyncio.sleep(0.05)
        yield b"JYZROX_FILE\t/data/b.jpg\tbbb\n"

    proc.stdout = _stdout()
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

        return await GalleryDlPlugin().download(
            url="https://example.com/x", dest_dir=tmp_path, credentials={}, on_file=on_file
        )


async def test_stdout_drained_after_process_exit(tmp_path):
    """A file is archived before its line is printed: a line written just before exit must still reach on_file."""
    seen: list[str] = []

    async def on_file(path, sha256=None):
        seen.append(path.name)

    result = await _download_with_late_line(tmp_path, on_file)

    assert seen == ["a.jpg", "b.jpg"]
    assert result.downloaded == 2


async def test_stdout_reader_still_open_after_the_drain_window_is_cancelled_not_awaited_forever(tmp_path):
    """The window only guards a descendant holding the pipe open; once it lapses the reader is cancelled."""
    seen: list[str] = []

    async def on_file(path, sha256=None):
        seen.append(path.name)

    with patch("plugins.builtin.gallery_dl.source._READER_DRAIN_TIMEOUT_S", 0):
        result = await _download_with_late_line(tmp_path, on_file)

    assert "b.jpg" not in seen  # the late line is dropped, which also shows the test above can fail
    assert result.status in ("done", "partial", "failed")
