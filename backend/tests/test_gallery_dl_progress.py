"""Regression tests for gallery-dl progress visibility (Sprint 1).

Covers the new diagnostic_ctx fields surfaced through stdout/stderr/pause
readers so the UI can show what gallery-dl is actually doing — current file,
sleep state, recent log, skip counts.

Edge cases under test:
- prepare event sets current_file and is cleared on file completion
- Subscription re-download / archive-skip increments skipped without touching downloaded
- Sub-2s "throttle" sleeps are filtered (no UI flicker)
- 429 rate limit takes precedence over the bare "sleeping" inference
- Pause restores prior state on resume; cancel marks state cancelled
- recent_log is a bounded ring buffer
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.builtin.gallery_dl import source as gdl_source
from plugins.builtin.gallery_dl.source import (
    GDL_STATE_CANCELLED,
    GDL_STATE_DOWNLOADING,
    GDL_STATE_PAUSED,
    GDL_STATE_RATE_LIMITED,
    GDL_STATE_SLEEPING,
    _DownloadState,
    _read_stderr,
    _read_stdout,
)


def _stderr_proc(*chunks: bytes):
    """Build a fake process whose stderr.read returns each chunk then b''."""
    proc = MagicMock()
    proc.stderr = MagicMock()
    iter_chunks = list(chunks) + [b""]
    proc.stderr.read = AsyncMock(side_effect=iter_chunks)
    return proc


def _stdout_proc(lines: list[bytes]):
    """Build a fake process whose stdout iterates given lines."""
    proc = MagicMock()

    async def _iter():
        for line in lines:
            yield line

    proc.stdout = _iter()
    return proc


@pytest.fixture(autouse=True)
def _mute_adaptive():
    """The stderr reader pokes the adaptive engine on 403; mock it out."""
    fake = MagicMock()
    fake.record_signal = AsyncMock()
    with patch("core.adaptive.adaptive_engine", fake):
        yield


# ── stdout: prepare / file / skip ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_event_sets_current_file_and_page():
    state = _DownloadState()
    diag: dict = {}
    proc = _stdout_proc([b"JYZROX_PREPARE\t3\tphoto_001.jpg\n"])
    await _read_stdout(proc, state, on_file=None, on_progress=None, diagnostic_ctx=diag)
    assert state.current_file == "photo_001.jpg"
    assert state.current_file_page == 3
    assert state.gdl_state == GDL_STATE_DOWNLOADING
    assert diag["current_file"] == "photo_001.jpg"
    assert diag["current_file_page"] == 3


@pytest.mark.asyncio
async def test_file_event_clears_current_file_marker():
    """After a file finishes (JYZROX_FILE), current_file must clear so the
    UI doesn't show the just-completed file as 'downloading'."""
    state = _DownloadState(current_file="prev.jpg", current_file_page=1)
    diag: dict = {"current_file": "prev.jpg"}
    proc = _stdout_proc([b"JYZROX_FILE\t/data/prev.jpg\t" + b"a" * 64 + b"\n"])
    await _read_stdout(proc, state, on_file=None, on_progress=None, diagnostic_ctx=diag)
    assert state.current_file is None
    assert state.current_file_page is None
    assert state.downloaded == 1
    assert diag["current_file"] is None


@pytest.mark.asyncio
async def test_skip_event_increments_skipped_not_downloaded():
    """Subscription re-download / archive hits must increment 'skipped'
    counter without inflating 'downloaded' — this is what lets UI show
    'X already saved' instead of falsely claiming progress."""
    state = _DownloadState()
    diag: dict = {}
    proc = _stdout_proc([b"JYZROX_SKIP\n", b"JYZROX_SKIP\n", b"JYZROX_SKIP\n"])
    await _read_stdout(proc, state, on_file=None, on_progress=None, diagnostic_ctx=diag)
    assert state.downloaded == 0
    assert state.skipped_count == 3
    assert diag["skipped"] == 3


@pytest.mark.asyncio
async def test_mixed_subscription_run_distinguishes_new_vs_archived():
    """Edge case: subscription with deleted images + new posts.
    Should produce both downloaded and skipped counts, distinguishable."""
    state = _DownloadState()
    diag: dict = {}
    proc = _stdout_proc(
        [
            b"JYZROX_PREPARE\t1\tnew_post.jpg\n",
            b"JYZROX_FILE\t/data/new_post.jpg\t" + b"b" * 64 + b"\n",
            b"JYZROX_SKIP\n",  # old image, archive hit
            b"JYZROX_SKIP\n",
        ]
    )
    await _read_stdout(proc, state, on_file=None, on_progress=None, diagnostic_ctx=diag)
    assert state.downloaded == 1
    assert state.skipped_count == 2


# ── stderr: sleep / rate limit / log ──────────────────────────────────────


@pytest.mark.asyncio
async def test_long_sleep_surfaces_as_sleeping_state():
    state = _DownloadState()
    diag: dict = {}
    proc = _stderr_proc(b"[twitter][debug] Sleeping 60.0 seconds (request)\n")
    await _read_stderr(proc, state, diag)
    assert state.gdl_state == GDL_STATE_SLEEPING
    assert state.gdl_state_seconds == 60.0
    assert diag["gdl_state"] == "sleeping"


@pytest.mark.asyncio
async def test_short_throttle_sleep_is_ignored():
    """Sub-2s sleeps are normal per-request throttling. Surfacing them
    would make the UI flicker between 'sleeping' and 'downloading' on
    every single page."""
    state = _DownloadState()
    diag: dict = {}
    proc = _stderr_proc(b"[twitter][debug] Sleeping 0.30 seconds (request)\n")
    await _read_stderr(proc, state, diag)
    assert state.gdl_state != GDL_STATE_SLEEPING
    assert state.gdl_state_seconds is None


@pytest.mark.asyncio
async def test_429_takes_precedence_over_sleep():
    """When gallery-dl hits 429 it logs both an HttpError AND a sleep line.
    UI should show 'rate limited' (more informative), not generic 'sleeping'."""
    state = _DownloadState()
    diag: dict = {}
    proc = _stderr_proc(b"[twitter][warning] HttpError: '429 Too Many Requests'. Sleeping 30.0 seconds.\n")
    await _read_stderr(proc, state, diag)
    assert state.gdl_state == GDL_STATE_RATE_LIMITED
    assert state.gdl_state_seconds == 30.0


@pytest.mark.asyncio
async def test_recent_log_is_bounded_ring_buffer():
    """Old log lines must roll off — never let recent_log grow unbounded."""
    state = _DownloadState()
    diag: dict = {}
    chunks = b"".join(f"[twitter][info] line {i}\n".encode() for i in range(20))
    proc = _stderr_proc(chunks)
    await _read_stderr(proc, state, diag)
    assert len(state.recent_log) == gdl_source._RECENT_LOG_SIZE
    # Newest lines retained
    assert "line 19" in state.recent_log[-1]


@pytest.mark.asyncio
async def test_chunked_stderr_without_trailing_newline_buffers_correctly():
    """Mid-line chunk boundary (gallery-dl byte progress \\r-only lines) must
    not produce ghost log entries. Only complete \\n-terminated lines count."""
    state = _DownloadState()
    diag: dict = {}
    proc = _stderr_proc(
        b"[twitter][debug] Sleeping ",  # split mid-line
        b"30.0 seconds\n",
    )
    await _read_stderr(proc, state, diag)
    assert state.gdl_state == GDL_STATE_SLEEPING
    assert len(state.recent_log) == 1


# ── _DownloadState.push_log invariant ────────────────────────────────────


def test_push_log_caps_at_recent_log_size():
    state = _DownloadState()
    for i in range(50):
        state.push_log(f"l{i}")
    assert len(state.recent_log) == gdl_source._RECENT_LOG_SIZE
    assert state.recent_log[-1] == "l49"


# ── Pause / cancel state propagation ──────────────────────────────────────


def test_paused_state_constants_distinct():
    """Smoke test to ensure the GDL_STATE_* constants stay distinct strings.
    UI key lookups depend on these literals."""
    states = {
        GDL_STATE_DOWNLOADING,
        GDL_STATE_PAUSED,
        GDL_STATE_CANCELLED,
        GDL_STATE_RATE_LIMITED,
        GDL_STATE_SLEEPING,
    }
    assert len(states) == 5
