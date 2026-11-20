"""gallery-dl subprocess progress state and constants."""

import re
from dataclasses import dataclass, field

_PRINT_FILE_PREFIX = "JYZROX_FILE\t"
_PRINT_SKIP_PREFIX = "JYZROX_SKIP"
_PRINT_PREPARE_PREFIX = "JYZROX_PREPARE\t"
_PROGRESS_EVERY_N = 5
_PROGRESS_EVERY_S = 10.0
_MAX_STDERR_LINES = 10000
_RECENT_LOG_SIZE = 5
_SLEEP_VISIBLE_THRESHOLD = 2.0
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Diagnostic state strings — surfaced to UI via progress dict
GDL_STATE_STARTING = "starting"
GDL_STATE_DOWNLOADING = "downloading"
GDL_STATE_SLEEPING = "sleeping"
GDL_STATE_RATE_LIMITED = "rate_limited"
GDL_STATE_RETRYING = "retrying"
GDL_STATE_PAUSED = "paused"
GDL_STATE_CANCELLED = "cancelled"

# Stderr inference patterns. gallery-dl uses Python logging with
# "[extractor][level] message" format, but underlying URL libs may emit
# different formats. Patterns kept lenient.
_RE_SLEEP = re.compile(r"[Ss]leeping\s+(\d+\.?\d*)\s+seconds?")
_RE_HTTP_STATUS = re.compile(r"\b(?:HttpError|HTTPError|HTTP\s*Error|status\s*code|HTTP/[\d.]+)[\D]{0,30}?(\d{3})\b")


@dataclass
class _DownloadState:
    """Shared mutable state for the download task group."""

    downloaded: int = 0
    skipped_count: int = 0
    last_activity: float = 0.0
    total_paused: float = 0.0
    cancelled: bool = False
    # True while the pause watcher holds the process in SIGSTOP; a stopped
    # process is silent by design, so the inactivity watchdog must not count it.
    paused: bool = False
    last_progress_update: float = 0.0
    stderr_lines: list[str] = field(default_factory=list)
    html_response_count: int = 0
    empty_response_count: int = 0
    source_id: str = ""
    last_page_time: float = 0.0
    # Diagnostic visibility — surfaced to UI via diagnostic_ctx
    current_file: str | None = None
    current_file_page: int | None = None
    gdl_state: str = GDL_STATE_STARTING
    gdl_state_seconds: float | None = None
    gdl_state_started_at: float = 0.0
    recent_log: list[str] = field(default_factory=list)
    # HTTP 403/429 seen on stderr; read by the persona cooldown (ADR 0022).
    throttle_signals: set[str] = field(default_factory=set)

    def push_log(self, line: str) -> None:
        self.recent_log.append(line)
        if len(self.recent_log) > _RECENT_LOG_SIZE:
            self.recent_log.pop(0)


def _sync_diagnostic(state: _DownloadState, diagnostic_ctx: dict | None) -> None:
    """Mirror state diagnostic fields into the shared ctx dict.

    Called from stdout/stderr/pause readers whenever state mutates so the
    on_progress closure (in worker.download) sees a consistent snapshot.
    """
    if diagnostic_ctx is None:
        return
    diagnostic_ctx["gdl_state"] = state.gdl_state
    diagnostic_ctx["current_file"] = state.current_file
    diagnostic_ctx["current_file_page"] = state.current_file_page
    diagnostic_ctx["downloaded"] = state.downloaded
    diagnostic_ctx["skipped"] = state.skipped_count
    diagnostic_ctx["filtered_html"] = state.html_response_count
    diagnostic_ctx["filtered_empty"] = state.empty_response_count
    if state.gdl_state_seconds is not None:
        diagnostic_ctx["gdl_state_seconds"] = state.gdl_state_seconds
    else:
        diagnostic_ctx.pop("gdl_state_seconds", None)
    diagnostic_ctx["throttle_signals"] = sorted(state.throttle_signals)
    diagnostic_ctx["recent_log"] = list(state.recent_log)
