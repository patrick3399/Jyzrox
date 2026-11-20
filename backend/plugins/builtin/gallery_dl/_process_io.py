"""gallery-dl subprocess output readers and file validation."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from plugins.builtin.gallery_dl._process_control import _terminate_process_tree
from plugins.builtin.gallery_dl._process_state import (
    _MAX_STDERR_LINES,
    _PRINT_FILE_PREFIX,
    _PRINT_PREPARE_PREFIX,
    _PRINT_SKIP_PREFIX,
    _PROGRESS_EVERY_N,
    _PROGRESS_EVERY_S,
    _RE_HTTP_STATUS,
    _RE_SLEEP,
    _SHA256_RE,
    _SLEEP_VISIBLE_THRESHOLD,
    GDL_STATE_DOWNLOADING,
    GDL_STATE_RATE_LIMITED,
    GDL_STATE_RETRYING,
    GDL_STATE_SLEEPING,
    _DownloadState,
    _sync_diagnostic,
)

logger = logging.getLogger(__name__)


async def _read_stdout(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
    on_file: Callable[[Path, str | None], Awaitable[None]] | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None,
    timing_ctx: dict | None = None,
    diagnostic_ctx: dict | None = None,
) -> None:
    """Parse structured --Print output from gallery-dl. No regex needed."""
    assert proc.stdout is not None

    async for raw_line in proc.stdout:
        now = asyncio.get_running_loop().time()
        if timing_ctx is not None:
            timing_ctx["idle_ms"] = round((now - state.last_activity) * 1000) if state.last_activity > 0 else 0
            timing_ctx["total_pause_ms"] = round(state.total_paused * 1000)
        state.last_activity = now
        line = raw_line.decode("utf-8", errors="replace").rstrip()

        if line.startswith(_PRINT_FILE_PREFIX):
            parts = line[len(_PRINT_FILE_PREFIX) :].split("\t", 1)
            file_path = Path(parts[0])
            sha256 = parts[1] if len(parts) > 1 and _SHA256_RE.fullmatch(parts[1]) else None

            state.downloaded += 1
            # File done — clear "currently downloading" marker so UI doesn't show stale name
            state.current_file = None
            state.current_file_page = None
            state.gdl_state = GDL_STATE_DOWNLOADING
            state.gdl_state_seconds = None
            if timing_ctx is not None:
                if state.last_page_time > 0:
                    timing_ctx["last_page_ms"] = round((now - state.last_page_time) * 1000)
                state.last_page_time = now
            _sync_diagnostic(state, diagnostic_ctx)

            if on_file:
                try:
                    await _on_file_with_validation(file_path, sha256, state, proc, on_file)
                except Exception as exc:
                    logger.warning("[gallery_dl] progressive import error: %s", exc)

        elif line.startswith(_PRINT_PREPARE_PREFIX):
            # Fired right before gallery-dl downloads a file. Format is
            # "JYZROX_PREPARE\t{num}\t{filename}". Either field may be empty
            # for extractors that don't populate {num} or {filename}.
            parts = line[len(_PRINT_PREPARE_PREFIX) :].split("\t", 2)
            page_str = parts[0] if parts else ""
            filename = parts[1] if len(parts) > 1 else ""
            try:
                state.current_file_page = int(page_str) if page_str.isdigit() else None
            except ValueError:
                state.current_file_page = None
            state.current_file = filename or None
            # Don't downgrade rate_limited/sleeping into downloading — the
            # next prepare arriving means gallery-dl resumed on its own.
            state.gdl_state = GDL_STATE_DOWNLOADING
            state.gdl_state_seconds = None
            _sync_diagnostic(state, diagnostic_ctx)

        elif line.startswith(_PRINT_SKIP_PREFIX):
            state.skipped_count += 1
            _sync_diagnostic(state, diagnostic_ctx)

        total_seen = state.downloaded + state.skipped_count
        if total_seen > 0 and (
            total_seen % _PROGRESS_EVERY_N == 0 or (now - state.last_progress_update) >= _PROGRESS_EVERY_S
        ):
            state.last_progress_update = now
            if on_progress is not None:
                try:
                    await on_progress(total_seen, 0)
                except Exception:
                    pass


async def _read_stderr(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
    diagnostic_ctx: dict | None = None,
) -> None:
    """Accumulate stderr for error reporting. Infer high-level state for UI.

    v3.0: rate-limit signals (429/503/timeout) offloaded to gallery-dl's
    native sleep-429 and sleep-retries config. The adaptive engine still
    tracks 403 (credential warning); additionally we infer transient state
    (sleeping / rate_limited / retrying) for UI visibility, but DO NOT act
    on it — gallery-dl handles the actual recovery.
    """
    assert proc.stderr is not None
    from core.adaptive import _RE_403, AdaptiveSignal, adaptive_engine

    # Read by chunks (not lines) so \r-only progress bars also reset last_activity.
    buf = b""
    while True:
        chunk = await proc.stderr.read(4096)
        if not chunk:
            break
        state.last_activity = asyncio.get_running_loop().time()
        buf += chunk
        # Process complete lines only (split on \n; keep incomplete tail in buf)
        parts = buf.split(b"\n")
        buf = parts[-1]
        for raw_line in parts[:-1]:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            if len(state.stderr_lines) < _MAX_STDERR_LINES:
                state.stderr_lines.append(line)
            state.push_log(line)

            is_403 = _RE_403.search(line) is not None
            if is_403:
                state.throttle_signals.add("http_403")
            if state.source_id and is_403:
                try:
                    await adaptive_engine.record_signal(state.source_id, AdaptiveSignal.HTTP_403)
                except Exception:
                    pass

            # State inference — order matters: explicit status codes outrank
            # generic "sleeping" since 429 sleeps include the word "sleep".
            m_status = _RE_HTTP_STATUS.search(line)
            m_sleep = _RE_SLEEP.search(line)
            if m_status:
                try:
                    code = int(m_status.group(1))
                except ValueError, IndexError:
                    code = 0
                if code == 429:
                    state.throttle_signals.add("http_429")
                    state.gdl_state = GDL_STATE_RATE_LIMITED
                    if m_sleep:
                        state.gdl_state_seconds = float(m_sleep.group(1))
                    state.gdl_state_started_at = asyncio.get_running_loop().time()
                elif code in (502, 503, 504):
                    state.gdl_state = GDL_STATE_RETRYING
                    state.gdl_state_started_at = asyncio.get_running_loop().time()
            elif m_sleep:
                seconds = float(m_sleep.group(1))
                # Sub-2s sleeps are normal per-request throttling — don't
                # surface them or the UI would flicker constantly.
                if seconds >= _SLEEP_VISIBLE_THRESHOLD:
                    state.gdl_state = GDL_STATE_SLEEPING
                    state.gdl_state_seconds = seconds
                    state.gdl_state_started_at = asyncio.get_running_loop().time()

            _sync_diagnostic(state, diagnostic_ctx)


def _validate_download_content(file_path: Path) -> str | None:
    """Check downloaded file content. Returns 'html', 'empty', or None (ok)."""
    try:
        size = file_path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return "empty"
    if size < 102400:  # < 100KB
        try:
            head = file_path.read_bytes()[:512]
            text = head.decode("utf-8", errors="replace").lower()
            if "<!doctype" in text or "<html" in text or "cf-browser-verification" in text:
                return "html"
        except OSError:
            pass
    return None


async def _on_file_with_validation(
    file_path: Path,
    sha256: str | None,
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    inner_on_file: Callable[[Path, str | None], Awaitable[None]] | None,
) -> None:
    """Wrap on_file with content validation + adaptive feedback."""
    from core.adaptive import AdaptiveSignal, adaptive_engine

    result = _validate_download_content(file_path)
    if result == "html":
        state.html_response_count += 1
        if state.source_id:
            try:
                await adaptive_engine.record_signal(state.source_id, AdaptiveSignal.HTML_RESPONSE)
            except Exception:
                pass
        if state.html_response_count >= 5:
            logger.warning(
                "[gallery_dl] too many HTML responses (%d) — killing process",
                state.html_response_count,
            )
            state.cancelled = True
            await _terminate_process_tree(proc)
        elif state.html_response_count >= 3:
            from core.events import EventType, emit_safe

            await emit_safe(
                EventType.ADAPTIVE_BLOCKED,
                resource_type="download",
                source_id=state.source_id,
                html_response_count=state.html_response_count,
            )
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    elif result == "empty":
        state.empty_response_count += 1
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    if inner_on_file:
        await inner_on_file(file_path, sha256)
