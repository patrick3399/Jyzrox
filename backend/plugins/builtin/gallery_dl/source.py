"""gallery-dl fallback SourcePlugin.

Wraps the existing gallery-dl subprocess logic so it participates in the
plugin registry while preserving all existing behaviour (PID tracking,
cancel support, progress reporting, config file generation).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from core.version import __version__
from plugins.base import SourcePlugin
from plugins.builtin.gallery_dl._archive_jobs import _ensure_job_archive_table, _prepare_repair_archive
from plugins.builtin.gallery_dl._config import _build_gallery_dl_config
from plugins.builtin.gallery_dl._metadata import _resolve_source_id
from plugins.builtin.gallery_dl._process_control import (
    _heartbeat_loop,
    _inactivity_watchdog,
    _pause_cancel_watcher,
    _terminate_process_tree,
)
from plugins.builtin.gallery_dl._process_io import _read_stderr, _read_stdout
from plugins.builtin.gallery_dl._process_state import _PRINT_SKIP_PREFIX, _DownloadState, _sync_diagnostic
from plugins.builtin.gallery_dl._subprocess_env import gdl_subprocess_env
from plugins.models import (
    CredentialFlow,
    CredentialStatus,
    DownloadResult,
    GalleryImportData,
    GalleryMetadata,
    PluginMeta,
    SiteInfo,
)
from services.download_mode import REPAIR, effective_mode
from services.download_policy import media_policy_from_options

logger = logging.getLogger(__name__)

_PROGRESS_PULSE_S = 5.0
_READER_DRAIN_TIMEOUT_S = 10


def _build_supported_sites() -> list[SiteInfo]:
    """Generate SiteInfo list from unified site registry."""
    from plugins.builtin.gallery_dl._sites import all_sites

    return [
        SiteInfo(
            domain=s.domain,
            source_id=s.source_id,
            name=s.name,
            category=s.category,
            has_tags=s.has_tags,
        )
        for s in all_sites()
    ]


def _source_to_extractor(source: str) -> str:
    """Map our source name to gallery-dl extractor name."""
    from plugins.builtin.gallery_dl._sites import gdl_extractor_name

    return gdl_extractor_name(source)


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

    supports_media_policy = True

    meta = PluginMeta(
        name="gallery-dl (Fallback)",
        source_id="gallery_dl",
        version=__version__,
        description="Universal gallery-dl fallback downloader",
        url_patterns=[],  # handles everything — it is the fallback
        credential_schema=[],
        supported_sites=_build_supported_sites(),
        concurrency=1,
        semaphore_key="gallery_dl",
        needs_all_credentials=True,
    )

    def __init__(self) -> None:
        # The class attribute was built when this module was imported, which is
        # before init_plugins() registers the sites drop-in extractors declare.
        self.meta = self.meta.model_copy(update={"supported_sites": _build_supported_sites()})

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

        # Resolve the job's target site up front — global downloader options
        # in the config (rate) must be scoped to this site only.
        from urllib.parse import urlparse as _urlparse

        from plugins.builtin.gallery_dl._sites import get_site_by_domain

        _domain = _urlparse(url).netloc.removeprefix("www.")
        _site_cfg = get_site_by_domain(_domain)

        # Fail a malformed stored policy loudly instead of silently downloading everything.
        try:
            media = media_policy_from_options(options)
        except ValueError as exc:
            return DownloadResult(status="failed", downloaded=0, total=0, error=f"Invalid media options: {exc}")

        # The worker stamps the job's mode into options; a caller that does not
        # falls back to the legacy flags (force_full_scan -> repair).
        mode = effective_mode((options or {}).get("mode"), options)

        if archive_error := await _ensure_job_archive_table(url):
            logger.error("[gallery_dl] refusing download of %s: %s", url, archive_error)
            return DownloadResult(status="failed", downloaded=0, total=0, error=archive_error)
        archive_table = await _prepare_repair_archive(url, (options or {}).get("config_id")) if mode == REPAIR else None

        config_path = await _build_gallery_dl_config(
            credentials,
            config_id=options.get("config_id") if options else None,
            job_context=options.get("job_context", "manual") if options else "manual",
            last_completed_at=options.get("last_completed_at") if options else None,
            target_source_id=_site_cfg.source_id,
            media=media,
            persona=(options or {}).get("persona"),
            mode=mode,
            archive_table=archive_table,
        )

        from worker.gallery_dl_venv import get_gdl_exec_cmd

        config_id = (options or {}).get("config_id")

        cmd = [
            *get_gdl_exec_cmd(),
            "--config-ignore",
            "--config",
            str(config_path),
            "--directory",
            str(dest_dir),
            "--Print",
            "after:JYZROX_FILE\t{_path}\t{sha256}",
            # The format needs a field: gallery-dl reads one with no "{" and no
            # space as a field *name* and prints that field's value instead.
            "--Print",
            f"skip:{_PRINT_SKIP_PREFIX}\t{{filename}}",
            # prepare event fires before each download — gives UI the file
            # name and page number while bytes are streaming in.
            "--Print",
            "prepare:JYZROX_PREPARE\t{num!s}\t{filename}",
        ]

        if config_id:
            cmd += ["--write-unsupported", f"/tmp/gdl-unsupported-{config_id}.txt"]
            cmd += ["--error-file", f"/tmp/gdl-errors-{config_id}.txt"]

        # Per-site download tuning via SiteConfigService
        from core.site_config import site_config_service

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
                # PYTHONPATH carries the Happy Eyeballs sitecustomize (_subprocess_env).
                env=gdl_subprocess_env(PYTHONUNBUFFERED="1"),
                # HR-011: start a new session so proc.pid == its process
                # group id. This lets every kill path below terminate the
                # whole descendant tree (ffmpeg, etc.) via os.killpg instead
                # of leaving orphans when only the top-level pid is killed.
                start_new_session=True,
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
            last_activity=asyncio.get_running_loop().time(),
            last_progress_update=asyncio.get_running_loop().time(),
            source_id=_site_cfg.source_id,
        )

        # Background reader tasks (these finish when the process's pipes close)
        timing_ctx = options.get("timing_ctx") if options else None
        diagnostic_ctx = options.get("diagnostic_ctx") if options else None
        if diagnostic_ctx is not None:
            # Seed initial state so the UI has something before first event arrives
            _sync_diagnostic(state, diagnostic_ctx)
        stdout_task = asyncio.create_task(_read_stdout(proc, state, on_file, on_progress, timing_ctx, diagnostic_ctx))
        stderr_task = asyncio.create_task(_read_stderr(proc, state, diagnostic_ctx))
        bg_tasks: list[asyncio.Task] = [stdout_task, stderr_task]

        # Periodic pulse so UI keeps refreshing during long sleeps / silent waits
        async def _pulse_loop() -> None:
            while True:
                await asyncio.sleep(_PROGRESS_PULSE_S)
                if state.cancelled or on_progress is None:
                    continue
                try:
                    total_seen = state.downloaded + state.skipped_count
                    await on_progress(total_seen, 0)
                except Exception:
                    pass

        pulse_task = asyncio.create_task(_pulse_loop())
        bg_tasks.append(pulse_task)

        # Sentinel tasks — any of these finishing first triggers cleanup
        proc_wait_task = asyncio.create_task(proc.wait())
        inactivity_task = asyncio.create_task(_inactivity_watchdog(state, inactivity_timeout, proc, watch_dir=dest_dir))
        sentinel_tasks: list[asyncio.Task] = [proc_wait_task, inactivity_task]

        sem_heartbeat = (options or {}).get("sem_heartbeat")
        heartbeat_task: asyncio.Task | None = None
        if sem_heartbeat:
            heartbeat_task = asyncio.create_task(_heartbeat_loop(state, proc, sem_heartbeat))
            sentinel_tasks.append(heartbeat_task)

        if cancel_check or pause_check:
            sentinel_tasks.append(
                asyncio.create_task(_pause_cancel_watcher(state, proc, cancel_check, pause_check, diagnostic_ctx))
            )

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

        # Cancel the sentinels and the pulse task. The stdout/stderr readers are
        # NOT cancelled yet: gallery-dl records a file in the archive before its
        # `after` hook prints JYZROX_FILE, so a line still buffered in the pipe
        # when the process exits names a file that is archived and must reach
        # on_file, or the archive keeps a row for a file that was never imported.
        stoppable = pending | ({pulse_task} if not pulse_task.done() else set())
        for t in stoppable:
            t.cancel()
        if stoppable:
            await asyncio.wait(stoppable, timeout=5)

        # Wait for process to actually finish
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            await _terminate_process_tree(proc)

        # The process is gone, so its pipes reach EOF and the readers finish
        # their buffered lines. The timeout only guards a descendant that
        # inherited the pipe and outlived gallery-dl.
        readers = {t for t in (stdout_task, stderr_task) if not t.done()}
        if readers:
            await asyncio.wait(readers, timeout=_READER_DRAIN_TIMEOUT_S)
            stuck = {t for t in readers if not t.done()}
            for t in stuck:
                t.cancel()
            if stuck:
                logger.warning(
                    "[gallery_dl] output readers still open %ds after exit; cancelled", _READER_DRAIN_TIMEOUT_S
                )
                await asyncio.wait(stuck, timeout=5)

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
            if state.downloaded > 0 or state.skipped_count > 0:
                filtered = state.html_response_count + state.empty_response_count
                logger.warning(
                    "[gallery_dl] %d file(s) downloaded and %d skipped before failure — returning partial%s",
                    state.downloaded,
                    state.skipped_count,
                    f" (filtered={filtered}: html={state.html_response_count}, empty={state.empty_response_count})"
                    if filtered
                    else "",
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

        filtered = state.html_response_count + state.empty_response_count
        logger.info(
            "[gallery_dl] done: %s (downloaded=%d, skipped=%d%s)",
            url,
            state.downloaded,
            state.skipped_count,
            f", filtered={filtered}(html={state.html_response_count},empty={state.empty_response_count})"
            if filtered
            else "",
        )
        return DownloadResult(
            status="done",
            downloaded=state.downloaded,
            total=state.downloaded + state.skipped_count,
            unsupported_urls=unsupported_urls,
            error_urls=error_urls,
        )

    def resolve_output_dir(self, url: str, base_path: Path, job_id: str | None = None) -> Path:
        """Return a per-job staging dir under ``base_path``.

        gallery-dl does no URL-specific routing, but it must NOT stage into the
        shared gallery root: finalize()/cleanup() rmtree the download dir, and
        rmtree of the root wipes every concurrently-downloading gallery's staging
        dir (e.g. an EH gallery under ``base_path/ehentai/<gid>/``). A per-job
        subdir keeps each download's rmtree isolated.
        """
        return base_path / "gallery_dl" / (job_id or "default")

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
