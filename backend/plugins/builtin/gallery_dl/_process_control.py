"""gallery-dl subprocess termination and watchdog loops."""

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from plugins.builtin.gallery_dl._process_state import (
    GDL_STATE_CANCELLED,
    GDL_STATE_DOWNLOADING,
    GDL_STATE_PAUSED,
    _DownloadState,
    _sync_diagnostic,
)

logger = logging.getLogger(__name__)


async def _terminate_process_tree(proc: asyncio.subprocess.Process, *, grace: float = 5.0) -> None:
    """Terminate the process AND all of its descendants (HR-011).

    gallery-dl spawns child/grandchild processes (e.g. ffmpeg for video
    post-processing). Killing only the top-level process leaves those
    orphaned. The process is spawned with ``start_new_session=True`` so its
    pid is also its process group id — signalling the group takes down the
    whole tree.

    Sends SIGTERM to the group first and waits up to ``grace`` seconds for
    a clean exit, then escalates to SIGKILL. Always reaps the process
    (``await proc.wait()``) before returning. Safe to call multiple times
    or after the process has already exited (``ProcessLookupError`` is
    swallowed at every step).
    """
    pid = getattr(proc, "pid", None)
    pgid: int | None = None
    if type(pid) is int and pid > 1:
        try:
            candidate = os.getpgid(pid)
            # start_new_session=True guarantees pgid == pid. Never signal a
            # caller/shared group if that invariant is unexpectedly false.
            if candidate == pid:
                pgid = candidate
            else:
                logger.error(
                    "[gallery_dl] refusing to signal process group %s for pid %s: expected an isolated session",
                    candidate,
                    pid,
                )
        except ProcessLookupError:
            pass
    else:
        logger.error("[gallery_dl] refusing process-group signal for invalid pid: %r", pid)

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    except TimeoutError:
        pass

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        logger.error("[gallery_dl] process pid=%r pgid=%r did not exit after SIGKILL", pid, pgid)


async def _heartbeat_loop(
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    callback: Callable[[], Awaitable[bool]],
    interval: float = 30.0,
) -> str:
    """Periodically validate the admission fence. Returns 'evicted' if ownership is lost."""
    while True:
        await asyncio.sleep(interval)
        if state.cancelled:
            return "cancelled"
        try:
            alive = await callback()
            if not alive:
                logger.error("[gallery_dl] admission fence lost — killing process")
                state.cancelled = True
                await _terminate_process_tree(proc)
                return "evicted"
        except Exception as exc:
            logger.warning("[gallery_dl] heartbeat callback error: %s", exc)


def _partial_bytes(watch_dir: Path) -> int:
    """Total size of the files gallery-dl is still writing (``*.part``)."""
    total = 0
    try:
        with os.scandir(watch_dir) as entries:
            for entry in entries:
                if entry.name.endswith(".part"):
                    try:
                        total += entry.stat().st_size
                    except OSError:
                        continue
    except OSError:
        return 0
    return total


async def _inactivity_watchdog(
    state: _DownloadState,
    timeout: float,
    proc: asyncio.subprocess.Process,
    watch_dir: Path | None = None,
    poll_s: float = 10,
) -> str:
    """Kill the process after `timeout` seconds without output or download progress.

    gallery-dl prints nothing while one file is in flight, so a large file on a
    slow CDN looked idle and was killed mid-download. A growing ``*.part`` file
    in `watch_dir` counts as activity.
    """
    last_partial = 0
    while True:
        await asyncio.sleep(poll_s)
        if state.cancelled:
            return "cancelled"
        if state.paused:
            # Restart the idle window so it is measured from resume, not pause start.
            state.last_activity = asyncio.get_running_loop().time()
            continue
        if watch_dir is not None:
            partial = await asyncio.to_thread(_partial_bytes, watch_dir)
            if partial != last_partial:
                last_partial = partial
                if partial:
                    state.last_activity = asyncio.get_running_loop().time()
        elapsed = asyncio.get_running_loop().time() - state.last_activity
        if elapsed >= timeout:
            logger.error("[gallery_dl] inactivity timeout (%ds) — killing process", timeout)
            await _terminate_process_tree(proc)
            return "inactivity_timeout"


async def _pause_cancel_watcher(
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    cancel_check: Callable[[], Awaitable[bool]] | None,
    pause_check: Callable[[], Awaitable[bool]] | None,
    diagnostic_ctx: dict | None = None,
) -> str:
    """Poll for cancel/pause signals at high frequency."""
    while True:
        await asyncio.sleep(0.5)

        # Cancel check
        if cancel_check is not None and await cancel_check():
            state.cancelled = True
            state.gdl_state = GDL_STATE_CANCELLED
            _sync_diagnostic(state, diagnostic_ctx)
            logger.info("[gallery_dl] cancel detected, killing process")
            await _terminate_process_tree(proc)
            return "cancelled"

        # Pause: suspend reading by sending SIGSTOP, resume with SIGCONT
        if pause_check is not None and await pause_check():
            pause_start = asyncio.get_running_loop().time()
            prev_state = state.gdl_state
            state.gdl_state = GDL_STATE_PAUSED
            _sync_diagnostic(state, diagnostic_ctx)
            logger.info("[gallery_dl] pausing process")
            state.paused = True
            try:
                proc.send_signal(signal.SIGSTOP)
            except ProcessLookupError, OSError:
                pass

            while await pause_check():
                if cancel_check is not None and await cancel_check():
                    state.cancelled = True
                    state.gdl_state = GDL_STATE_CANCELLED
                    _sync_diagnostic(state, diagnostic_ctx)
                    state.paused = False
                    try:
                        proc.send_signal(signal.SIGCONT)
                    except ProcessLookupError, OSError:
                        pass
                    await _terminate_process_tree(proc)
                    return "cancelled"
                await asyncio.sleep(0.5)

            # Resume — restore prior state (or downloading if it was paused-from-paused)
            paused_duration = asyncio.get_running_loop().time() - pause_start
            state.total_paused += paused_duration
            state.last_activity = asyncio.get_running_loop().time()
            state.gdl_state = prev_state if prev_state != GDL_STATE_PAUSED else GDL_STATE_DOWNLOADING
            _sync_diagnostic(state, diagnostic_ctx)
            logger.info("[gallery_dl] resumed after %.1fs", paused_duration)
            state.paused = False
            try:
                proc.send_signal(signal.SIGCONT)
            except ProcessLookupError, OSError:
                pass
