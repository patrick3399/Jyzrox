"""gallery-dl fallback SourcePlugin.

Wraps the existing gallery-dl subprocess logic so it participates in the
plugin registry while preserving all existing behaviour (PID tracking,
cancel support, progress reporting, config file generation).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.config import settings
from plugins.base import SourcePlugin
from plugins.builtin.gallery_dl._metadata import _resolve_source_id
from plugins.models import (
    CredentialFlow,
    CredentialStatus,
    DownloadResult,
    GalleryImportData,
    GalleryMetadata,
    PluginMeta,
    SiteInfo,
)

logger = logging.getLogger(__name__)

_PRINT_FILE_PREFIX = "JYZROX_FILE\t"
_PRINT_SKIP_PREFIX = "JYZROX_SKIP"
_PROGRESS_EVERY_N = 5
_PROGRESS_EVERY_S = 10.0
_MAX_STDERR_LINES = 10000

# Fields included in the metadata postprocessor JSON output.
_METADATA_INCLUDE = (
    "category",
    "subcategory",
    "title",
    "title_en",
    "title_jpn",
    "tags",
    "tag_string",
    "description",
    "id",
    "gallery_id",
    "uploader",
    "user",
    "artist",
    "date",
    "posted_at",
    "count",
    "num",
    "rating",
    "language",
)


def _build_supported_sites() -> list[SiteInfo]:
    """Generate SiteInfo list from unified site registry."""
    from plugins.builtin.gallery_dl._sites import GDL_SITES

    return [
        SiteInfo(
            domain=s.domain,
            source_id=s.source_id,
            name=s.name,
            category=s.category,
            has_tags=s.has_tags,
        )
        for s in GDL_SITES
    ]


def _source_to_extractor(source: str) -> str:
    """Map our source name to gallery-dl extractor name."""
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    return cfg.extractor or cfg.source_id


FRAGMENT_KEYS = {"cookies", "username", "password", "refresh-token", "api-key"}


def _try_parse_fragment(cred_val: str) -> dict | None:
    """Try to parse a credential value as a gallery-dl config fragment (new format).

    Returns the parsed dict if it's a fragment, None otherwise.
    """
    try:
        parsed = json.loads(cred_val)
        if isinstance(parsed, dict) and (FRAGMENT_KEYS & parsed.keys()):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _is_fragment(cred_val: str) -> bool:
    """Check if a credential value is a gallery-dl config fragment (new format)."""
    return _try_parse_fragment(cred_val) is not None


async def _build_gallery_dl_config(
    credentials: dict,
    config_id: str | None = None,
    job_context: str = "manual",
    last_completed_at: datetime | None = None,
) -> Path:
    """Write gallery-dl config with v3.0 features: PG archive, native rate-limiting, postprocessors.

    Args:
        credentials: Dict mapping source name -> credential value string.
        config_id: Per-job config isolation key.
        job_context: "manual" or "subscription" — controls archive-mode and skip behavior.
        last_completed_at: For subscription context, enables date-after optimization.

    Returns:
        Path to the config file written.
    """
    from plugins.builtin.gallery_dl._sites import GDL_SITES, get_site_config

    config: dict = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
            "directory": [],
            # N1: PostgreSQL archive — tables pre-created in init.sql
            "archive": settings.gdl_archive_dsn,
            "archive-table": "{category}",
            # N3: native rate limiting (offloaded from adaptive engine)
            "sleep-429": 60,
            "sleep-retries": 10,
            # N4: content integrity
            "filesize-min": "1k",
            # N10b: file-unique prevents duplicate URLs within a single run
            "file-unique": True,
        },
        "downloader": {
            # N4: adjust-extensions ensures correct file extensions
            "adjust-extensions": True,
        },
        "postprocessors": [
            # N5: hash PP — sha256 streamed via --Print
            {"name": "hash", "algorithm": "sha256"},
            # N5: mtime PP — preserves original upload timestamp
            {"name": "mtime"},
            # N10d: metadata PP with include filter (replaces --write-metadata --write-tags)
            {"name": "metadata", "mode": "json", "include": list(_METADATA_INCLUDE)},
        ],
    }

    # N2: subscription optimization
    if job_context == "subscription":
        config["extractor"]["skip"] = "abort:10"
        # N10a: archive-mode memory for batch writes (subscription)
        config["extractor"]["archive-mode"] = "memory"
        if last_completed_at:
            config["extractor"]["date-after"] = last_completed_at.strftime("%Y-%m-%dT%H:%M:%S")

    # Inject per-site sleep-request via SiteConfigService
    from core.site_config import site_config_service

    all_params = await site_config_service.get_all_download_params()
    for site_cfg in GDL_SITES:
        params = all_params.get(site_cfg.source_id)
        if not params:
            continue
        ext = site_cfg.extractor or site_cfg.source_id
        entry = config["extractor"].setdefault(ext, {})

        if params.sleep_request is not None:
            entry["sleep-request"] = (
                list(params.sleep_request) if isinstance(params.sleep_request, tuple) else params.sleep_request
            )

        # N7: per-site browser profile for anti-bot defense
        if params.browser_profile:
            entry["browser"] = params.browser_profile

        # N7: per-site proxy
        if params.proxy_url:
            entry["proxy"] = params.proxy_url

    # Merge credentials on top
    for src, cred_val in credentials.items():
        if not cred_val:
            continue
        cfg = get_site_config(src)
        ext = cfg.extractor or cfg.source_id

        fragment = _try_parse_fragment(cred_val)
        if fragment is not None:
            config["extractor"].setdefault(ext, {}).update(fragment)
            if "cookies" in fragment:
                for extra in cfg.extra_extractors:
                    config["extractor"].setdefault(extra, {})["cookies"] = fragment["cookies"]
                # N8: cookies-update for sources with cookie auth
                config["extractor"][ext]["cookies-update"] = True
        else:
            if cfg.credential_type == "refresh_token":
                config["extractor"].setdefault(ext, {})["refresh-token"] = cred_val
            elif cfg.credential_type == "cookies":
                try:
                    cookies = json.loads(cred_val)
                    config["extractor"].setdefault(ext, {})["cookies"] = cookies
                    for extra in cfg.extra_extractors:
                        config["extractor"].setdefault(extra, {})["cookies"] = cookies
                    # N8: cookies-update for legacy format too
                    config["extractor"][ext]["cookies-update"] = True
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[gallery_dl] invalid cookie JSON for source %s, skipping", src)

    # N6: ugoira PP for Pixiv (convert animated illustrations to MP4)
    if "pixiv" in credentials and credentials["pixiv"]:
        config["postprocessors"].append(
            {
                "name": "ugoira",
                "ffmpeg-output": True,
                "extension": "mp4",
            }
        )

    config_dir = Path(settings.gallery_dl_config).parent
    config_path = config_dir / f"gallery-dl-{config_id}.json" if config_id else Path(settings.gallery_dl_config)
    tmp_path = config_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2))
    os.rename(tmp_path, config_path)
    return config_path


@dataclass
class _DownloadState:
    """Shared mutable state for the download task group."""

    downloaded: int = 0
    skipped_count: int = 0
    last_activity: float = 0.0
    total_paused: float = 0.0
    cancelled: bool = False
    last_progress_update: float = 0.0
    stderr_lines: list[str] = field(default_factory=list)
    html_response_count: int = 0
    source_id: str = ""
    last_page_time: float = 0.0


async def _read_stdout(
    proc: asyncio.subprocess.Process,
    state: _DownloadState,
    on_file: Callable[[Path, str | None], Awaitable[None]] | None,
    on_progress: Callable[[int, int], Awaitable[None]] | None,
    timing_ctx: dict | None = None,
) -> None:
    """Parse structured --Print output from gallery-dl. No regex needed."""
    assert proc.stdout is not None

    async for raw_line in proc.stdout:
        now = asyncio.get_event_loop().time()
        if timing_ctx is not None:
            timing_ctx["idle_ms"] = round((now - state.last_activity) * 1000) if state.last_activity > 0 else 0
            timing_ctx["total_pause_ms"] = round(state.total_paused * 1000)
        state.last_activity = now
        line = raw_line.decode("utf-8", errors="replace").rstrip()

        if line.startswith(_PRINT_FILE_PREFIX):
            parts = line[len(_PRINT_FILE_PREFIX) :].split("\t", 1)
            file_path = Path(parts[0])
            sha256 = parts[1] if len(parts) > 1 and parts[1] else None

            state.downloaded += 1
            if timing_ctx is not None:
                if state.last_page_time > 0:
                    timing_ctx["last_page_ms"] = round((now - state.last_page_time) * 1000)
                state.last_page_time = now

            if on_file:
                try:
                    await _on_file_with_validation(file_path, sha256, state, proc, on_file)
                except Exception as exc:
                    logger.warning("[gallery_dl] progressive import error: %s", exc)

        elif line.startswith(_PRINT_SKIP_PREFIX):
            state.skipped_count += 1

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
) -> None:
    """Accumulate stderr for error reporting. Detect 403 for credential warnings only.

    v3.0: rate-limit signals (429/503/timeout) offloaded to gallery-dl's
    native sleep-429 and sleep-retries config. Only credential-related
    signals (403) are still tracked by the adaptive engine.
    """
    assert proc.stderr is not None
    from core.adaptive import _RE_403, AdaptiveSignal, adaptive_engine

    async for raw_line in proc.stderr:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        if line and len(state.stderr_lines) < _MAX_STDERR_LINES:
            state.stderr_lines.append(line)
        if state.source_id and _RE_403.search(line):
            try:
                await adaptive_engine.record_signal(state.source_id, AdaptiveSignal.HTTP_403)
            except Exception:
                pass


async def _heartbeat_loop(
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    callback: Callable[[], Awaitable[bool]],
    interval: float = 30.0,
) -> str:
    """Periodically call semaphore heartbeat. Returns 'evicted' if slot lost."""
    while True:
        await asyncio.sleep(interval)
        if state.cancelled:
            return "cancelled"
        try:
            alive = await callback()
            if not alive:
                logger.error("[gallery_dl] semaphore eviction — killing process")
                state.cancelled = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return "evicted"
        except Exception as exc:
            logger.warning("[gallery_dl] heartbeat callback error: %s", exc)


async def _inactivity_watchdog(
    state: _DownloadState,
    timeout: int,
    proc: asyncio.subprocess.Process,
) -> str:
    """Kill the process if no stdout/stderr activity for `timeout` seconds."""
    while True:
        await asyncio.sleep(10)
        if state.cancelled:
            return "cancelled"
        elapsed = asyncio.get_event_loop().time() - state.last_activity
        if elapsed >= timeout:
            logger.error("[gallery_dl] inactivity timeout (%ds) — killing process", timeout)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return "inactivity_timeout"


async def _pause_cancel_watcher(
    state: _DownloadState,
    proc: asyncio.subprocess.Process,
    cancel_check: Callable[[], Awaitable[bool]] | None,
    pause_check: Callable[[], Awaitable[bool]] | None,
) -> str:
    """Poll for cancel/pause signals at high frequency."""
    while True:
        await asyncio.sleep(0.5)

        # Cancel check
        if cancel_check is not None and await cancel_check():
            state.cancelled = True
            logger.info("[gallery_dl] cancel detected, killing process")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return "cancelled"

        # Pause: suspend reading by sending SIGSTOP, resume with SIGCONT
        if pause_check is not None and await pause_check():
            import signal

            pause_start = asyncio.get_event_loop().time()
            logger.info("[gallery_dl] pausing process")
            try:
                proc.send_signal(signal.SIGSTOP)
            except (ProcessLookupError, OSError):
                pass

            while await pause_check():
                if cancel_check is not None and await cancel_check():
                    state.cancelled = True
                    try:
                        proc.send_signal(signal.SIGCONT)
                        proc.kill()
                    except (ProcessLookupError, OSError):
                        pass
                    return "cancelled"
                await asyncio.sleep(0.5)

            # Resume
            paused_duration = asyncio.get_event_loop().time() - pause_start
            state.total_paused += paused_duration
            state.last_activity = asyncio.get_event_loop().time()  # reset inactivity after resume
            logger.info("[gallery_dl] resumed after %.1fs", paused_duration)
            try:
                proc.send_signal(signal.SIGCONT)
            except (ProcessLookupError, OSError):
                pass


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
            try:
                proc.kill()
            except ProcessLookupError:
                pass
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
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    if inner_on_file:
        await inner_on_file(file_path, sha256)


def _read_url_file(path: Path) -> list[str]:
    """Read and delete a URL file (--write-unsupported / --error-file output)."""
    try:
        return [line.strip() for line in path.read_text().splitlines() if line.strip()]
    except OSError:
        return []
    finally:
        path.unlink(missing_ok=True)


class GalleryDlPlugin(SourcePlugin):
    """Fallback SourcePlugin that delegates to gallery-dl subprocess."""

    meta = PluginMeta(
        name="gallery-dl (Fallback)",
        source_id="gallery_dl",
        version="1.0.0",
        description="Universal gallery-dl fallback downloader",
        url_patterns=[],  # handles everything — it is the fallback
        credential_schema=[],
        supported_sites=_build_supported_sites(),
        concurrency=1,
        semaphore_key="gallery_dl",
        needs_all_credentials=True,
    )

    async def can_handle(self, url: str) -> bool:
        """Always returns True — gallery-dl is the universal fallback."""
        return True

    async def resolve_metadata(
        self,
        url: str,
        credentials: dict | str | None,
    ) -> GalleryImportData | None:
        """gallery-dl discovers metadata during download, not before."""
        return None

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
        pause_check: Callable[[], Awaitable[bool]] | None = None,
        on_file: Callable[[Path, str | None], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult:
        """Run gallery-dl as a subprocess and stream progress."""
        if credentials is None:
            credentials = {}

        config_path = await _build_gallery_dl_config(
            credentials,
            config_id=options.get("config_id") if options else None,
            job_context=options.get("job_context", "manual") if options else "manual",
            last_completed_at=options.get("last_completed_at") if options else None,
        )

        from worker.gallery_dl_venv import get_gdl_bin

        config_id = (options or {}).get("config_id")

        cmd = [
            get_gdl_bin(),
            "--config-ignore",
            "--config",
            str(config_path),
            "--directory",
            str(dest_dir),
            "--Print",
            "after:JYZROX_FILE\t{_path}\t{sha256}",
            "--Print",
            "skip:JYZROX_SKIP",
        ]

        if config_id:
            cmd += ["--write-unsupported", f"/tmp/gdl-unsupported-{config_id}.txt"]
            cmd += ["--error-file", f"/tmp/gdl-errors-{config_id}.txt"]

        # Per-site download tuning via SiteConfigService
        from urllib.parse import urlparse as _urlparse

        from core.site_config import site_config_service
        from plugins.builtin.gallery_dl._sites import get_site_by_domain

        _domain = _urlparse(url).netloc.removeprefix("www.")
        _site_cfg = get_site_by_domain(_domain)
        _dl_params = await site_config_service.get_effective_download_params(_site_cfg.source_id)

        if _dl_params.retries != 4:  # only add if non-default
            cmd += ["--retries", str(_dl_params.retries)]

        if _dl_params.http_timeout != 30:
            cmd += ["--http-timeout", str(_dl_params.http_timeout)]

        # Options-driven flags
        if options:
            if options.get("abort"):
                cmd += ["--abort", str(options["abort"])]
            if options.get("filesize_min"):
                cmd += ["--filesize-min", str(options["filesize_min"])]
            if options.get("filesize_max"):
                cmd += ["--filesize-max", str(options["filesize_max"])]

        cmd.append(url)

        # Resolve inactivity timeout: options override, then site config, then default
        inactivity_timeout: int = (options or {}).get("inactivity_timeout", _dl_params.inactivity_timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            err = f"Failed to start gallery-dl: {exc}"
            logger.error("[gallery_dl] %s", err)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)

        # Report PID for pause/resume support
        if pid_callback is not None:
            try:
                await pid_callback(proc.pid)
            except Exception as exc:
                logger.warning("[gallery_dl] pid_callback failed: %s", exc)

        state = _DownloadState(
            last_activity=asyncio.get_event_loop().time(),
            last_progress_update=asyncio.get_event_loop().time(),
            source_id=_site_cfg.source_id,
        )

        # Background reader tasks (these finish when the process's pipes close)
        timing_ctx = options.get("timing_ctx") if options else None
        stdout_task = asyncio.create_task(_read_stdout(proc, state, on_file, on_progress, timing_ctx))
        stderr_task = asyncio.create_task(_read_stderr(proc, state))
        bg_tasks: list[asyncio.Task] = [stdout_task, stderr_task]

        # Sentinel tasks — any of these finishing first triggers cleanup
        proc_wait_task = asyncio.create_task(proc.wait())
        inactivity_task = asyncio.create_task(_inactivity_watchdog(state, inactivity_timeout, proc))
        sentinel_tasks: list[asyncio.Task] = [proc_wait_task, inactivity_task]

        sem_heartbeat = (options or {}).get("sem_heartbeat")
        heartbeat_task: asyncio.Task | None = None
        if sem_heartbeat:
            heartbeat_task = asyncio.create_task(_heartbeat_loop(state, proc, sem_heartbeat))
            sentinel_tasks.append(heartbeat_task)

        if cancel_check or pause_check:
            sentinel_tasks.append(asyncio.create_task(_pause_cancel_watcher(state, proc, cancel_check, pause_check)))

        all_tasks = bg_tasks + sentinel_tasks
        try:
            done, pending = await asyncio.wait(
                sentinel_tasks,
                timeout=86400,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            for t in all_tasks:
                t.cancel()
            raise

        # Determine what finished first
        timed_out = len(done) == 0  # asyncio.wait timeout
        inactivity_killed = False

        for t in done:
            if t is inactivity_task:
                try:
                    result = t.result()
                    if result == "inactivity_timeout":
                        inactivity_killed = True
                except Exception:
                    pass

        evicted = False
        if heartbeat_task is not None:
            for t in done:
                if t is heartbeat_task:
                    try:
                        result = t.result()
                        if result == "evicted":
                            evicted = True
                    except Exception:
                        pass

        # Cancel all remaining tasks (sentinels + background)
        remaining = pending | {t for t in bg_tasks if not t.done()}
        for t in remaining:
            t.cancel()
        if remaining:
            await asyncio.wait(remaining, timeout=5)

        # Wait for process to actually finish
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

        # Capture unsupported + error URLs
        unsupported_urls: list[str] = []
        error_urls: list[str] = []
        if config_id:
            unsupported_urls = _read_url_file(Path(f"/tmp/gdl-unsupported-{config_id}.txt"))
            error_urls = _read_url_file(Path(f"/tmp/gdl-errors-{config_id}.txt"))

        # Result mapping
        if state.cancelled:
            logger.info("[gallery_dl] cancelled: %s (downloaded=%d)", url, state.downloaded)
            return DownloadResult(
                status="cancelled",
                downloaded=state.downloaded,
                total=state.downloaded,
                unsupported_urls=unsupported_urls,
                error_urls=error_urls,
            )

        if timed_out:
            return DownloadResult(
                status="failed",
                downloaded=state.downloaded,
                total=state.downloaded,
                error="download timeout after 86400s",
                unsupported_urls=unsupported_urls,
                error_urls=error_urls,
            )

        if inactivity_killed:
            err = f"No output for {inactivity_timeout}s — process killed"
            if state.downloaded > 0:
                return DownloadResult(
                    status="partial",
                    downloaded=state.downloaded,
                    total=state.downloaded + state.skipped_count,
                    error=err,
                    unsupported_urls=unsupported_urls,
                    error_urls=error_urls,
                )
            return DownloadResult(
                status="failed",
                downloaded=0,
                total=0,
                error=err,
                unsupported_urls=unsupported_urls,
                error_urls=error_urls,
            )

        if evicted:
            err = "Semaphore eviction — heartbeat lost"
            logger.error("[gallery_dl] %s: %s", err, url)
            return DownloadResult(
                status="failed",
                downloaded=state.downloaded,
                total=state.downloaded + state.skipped_count,
                error=err,
                unsupported_urls=unsupported_urls,
                error_urls=error_urls,
            )

        stderr_text = "\n".join(state.stderr_lines)

        if proc.returncode != 0:
            err = stderr_text[:500]
            logger.error("[gallery_dl] non-zero exit:\n%s", stderr_text)
            if state.downloaded > 0:
                logger.warning(
                    "[gallery_dl] %d file(s) downloaded before failure — returning partial",
                    state.downloaded,
                )
                return DownloadResult(
                    status="partial",
                    downloaded=state.downloaded,
                    total=state.downloaded + state.skipped_count,
                    error=err,
                    unsupported_urls=unsupported_urls,
                    error_urls=error_urls,
                )
            return DownloadResult(
                status="failed",
                downloaded=state.downloaded,
                total=state.downloaded + state.skipped_count,
                error=err,
                unsupported_urls=unsupported_urls,
                error_urls=error_urls,
            )

        logger.info("[gallery_dl] done: %s (downloaded=%d, skipped=%d)", url, state.downloaded, state.skipped_count)
        return DownloadResult(
            status="done",
            downloaded=state.downloaded,
            total=state.downloaded + state.skipped_count,
            unsupported_urls=unsupported_urls,
            error_urls=error_urls,
        )

    def resolve_output_dir(self, url: str, base_path: Path) -> Path:
        """gallery-dl uses a generic directory — no URL-specific routing."""
        return base_path

    def requires_credentials(self) -> bool:
        """gallery-dl doesn't strictly require credentials (works without them for many sites)."""
        return False

    def parse_import(self, dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
        """Parse a gallery-dl download into structured import data."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        return parse_gallery_dl_import(dest_dir, raw_meta)

    def credential_flows(self) -> list[CredentialFlow]:
        """Declare generic cookie credential flow."""
        from plugins.builtin.gallery_dl._credentials import gallery_dl_credential_flows

        return gallery_dl_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        """Generic cookie credentials can't be verified — always return valid."""
        from plugins.builtin.gallery_dl._credentials import verify_gallery_dl_credential

        return await verify_gallery_dl_credential(credentials)

    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        """Read the first *.json file gallery-dl wrote and return GalleryMetadata."""
        from plugins.builtin.gallery_dl._sites import get_site_config

        for meta_file in sorted(dest_dir.rglob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
                source = raw.get("category", "gallery_dl")
                cfg = get_site_config(source)

                tags = raw.get("tags", [])
                rating = raw.get("rating")
                if rating and isinstance(tags, list):
                    tags = list(tags)  # don't mutate original
                    tags.append(f"rating:{rating}")

                source_id = _resolve_source_id(raw, cfg, dest_dir.name)

                return GalleryMetadata(
                    source=source,
                    source_id=source_id,
                    title=raw.get("title") or raw.get("description") or dest_dir.name,
                    tags=tags,
                    pages=raw.get("count", 0),
                    uploader=raw.get("uploader") or raw.get("artist") or "",
                )
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                logger.warning("[gallery_dl] failed to read metadata %s: %s", meta_file, exc)
                continue
        return None
