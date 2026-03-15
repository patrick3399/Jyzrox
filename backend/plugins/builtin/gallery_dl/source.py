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
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from core.config import settings
from plugins.base import SourcePlugin
from plugins.models import (
    CredentialFlow,
    CredentialStatus,
    DownloadResult,
    FieldDef,
    GalleryImportData,
    GalleryMetadata,
    PluginMeta,
    SiteInfo,
)

logger = logging.getLogger(__name__)

_FILE_PATH_RE = re.compile(r"/data/")
_FILE_PATH_EXTRACT_RE = re.compile(r"(/data/.+\.\w+)")
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|avif|heic|mp4|webm)$", re.IGNORECASE)
_PROGRESS_EVERY_N = 5
_PROGRESS_EVERY_S = 10.0


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


async def _build_gallery_dl_config(credentials: dict) -> None:
    """Write source-specific credentials and tuning params into the gallery-dl config file.

    Args:
        credentials: Dict mapping source name -> credential value string.
                     e.g. {"ehentai": '{"ipb_member_id": ...}', "pixiv": "token..."}
    """
    from plugins.builtin.gallery_dl._sites import GDL_SITES, get_site_config

    config: dict = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
            "directory": [],
        },
    }

    # Inject per-site tuning params (sleep-request, retries, timeout) for ALL sites
    for site_cfg in GDL_SITES:
        if site_cfg.sleep_request is None:
            continue
        ext = site_cfg.extractor or site_cfg.source_id
        entry = config["extractor"].setdefault(ext, {})
        entry["sleep-request"] = list(site_cfg.sleep_request) if isinstance(site_cfg.sleep_request, tuple) else site_cfg.sleep_request

    # Merge credentials on top
    for src, cred_val in credentials.items():
        if not cred_val:
            continue
        cfg = get_site_config(src)
        ext = cfg.extractor or cfg.source_id

        if cfg.credential_type == "refresh_token":
            config["extractor"].setdefault(ext, {})["refresh-token"] = cred_val
        elif cfg.credential_type == "cookies":
            try:
                cookies = json.loads(cred_val)
                config["extractor"].setdefault(ext, {})["cookies"] = cookies
                for extra in cfg.extra_extractors:
                    config["extractor"].setdefault(extra, {})["cookies"] = cookies
            except (json.JSONDecodeError, TypeError):
                logger.warning("[gallery_dl] invalid cookie JSON for source %s, skipping", src)
        # credential_type == "none" → skip

    config_path = Path(settings.gallery_dl_config)
    tmp_path = config_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2))
    os.rename(tmp_path, config_path)


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
        on_file: Callable[[Path], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult:
        """Run gallery-dl as a subprocess and stream progress."""
        from core.redis_client import get_download_delay

        if credentials is None:
            credentials = {}

        await _build_gallery_dl_config(credentials)

        cmd = [
            "gallery-dl",
            "--config-ignore",
            "--config",
            settings.gallery_dl_config,
            "--write-metadata",
            "--write-tags",
            "--directory",
            str(dest_dir),
        ]

        delay_secs = await get_download_delay("gallery_dl", 0)
        if delay_secs > 0:
            cmd += ["--sleep-request", str(delay_secs)]

        # Download archive — skip already-downloaded URLs (unless skip_archive requested)
        if not (options and options.get("skip_archive")):
            from pathlib import Path as _Path
            archive_dir = _Path(settings.data_archive_path)
            archive_dir.mkdir(parents=True, exist_ok=True)
            cmd += ["--download-archive", str(archive_dir / "gallery-dl.db")]

        # Per-site download tuning
        from urllib.parse import urlparse as _urlparse
        from plugins.builtin.gallery_dl._sites import get_site_by_domain
        _domain = _urlparse(url).netloc.removeprefix("www.")
        _site_cfg = get_site_by_domain(_domain)
        if _site_cfg.retries != 4:  # only add if non-default
            cmd += ["--retries", str(_site_cfg.retries)]
        if _site_cfg.http_timeout != 30:  # only add if non-default
            cmd += ["--http-timeout", str(_site_cfg.http_timeout)]

        # Options-driven flags
        if options:
            if options.get("abort"):
                cmd += ["--abort", str(options["abort"])]
            if options.get("filesize_min"):
                cmd += ["--filesize-min", str(options["filesize_min"])]
            if options.get("filesize_max"):
                cmd += ["--filesize-max", str(options["filesize_max"])]

        cmd.append(url)

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

        downloaded = 0
        last_progress_update = asyncio.get_event_loop().time()
        started_at = asyncio.get_event_loop().time()
        total_paused = 0.0  # track pause duration to exclude from timeout

        async def _read_stdout() -> None:
            nonlocal downloaded, last_progress_update, total_paused
            assert proc.stdout is not None
            pending_file: Path | None = None

            async for raw_line in proc.stdout:
                # Check for cancellation at the top of every iteration
                if cancel_check is not None and await cancel_check():
                    logger.info("[gallery_dl] cancel detected in stdout loop, killing process: %s", url)
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    break

                # Soft-pause: stop reading stdout → pipe buffer fills → gallery-dl blocks
                if pause_check is not None:
                    pause_start = None
                    while await pause_check():
                        if pause_start is None:
                            pause_start = asyncio.get_event_loop().time()
                            logger.info("[gallery_dl] paused: %s", url)
                        if cancel_check is not None and await cancel_check():
                            break
                        await asyncio.sleep(0.5)
                    if pause_start is not None:
                        paused_duration = asyncio.get_event_loop().time() - pause_start
                        total_paused += paused_duration
                        logger.info("[gallery_dl] resumed after %.1fs: %s", paused_duration, url)

                line = raw_line.decode("utf-8", errors="replace").rstrip()

                # Lines starting with "# " are archive-skipped files — count but don't import
                skipped = line.startswith("# ")

                path_match = _FILE_PATH_EXTRACT_RE.search(line)
                if path_match or _FILE_PATH_RE.search(line) or _IMAGE_EXT_RE.search(line):
                    # Process the PREVIOUS pending file (guaranteed complete now that the next
                    # file line has appeared)
                    if pending_file is not None and on_file:
                        try:
                            await on_file(pending_file)
                        except Exception as exc:
                            logger.warning("[gallery_dl] progressive import error: %s", exc)

                    # Track the new pending file (only if actually downloaded, not skipped)
                    if path_match and not skipped:
                        pending_file = Path(path_match.group(1))
                    else:
                        pending_file = None

                    downloaded += 1
                    now = asyncio.get_event_loop().time()
                    if (
                        downloaded % _PROGRESS_EVERY_N == 0
                        or (now - last_progress_update) >= _PROGRESS_EVERY_S
                    ):
                        last_progress_update = now
                        if on_progress is not None:
                            try:
                                await on_progress(downloaded, 0)  # total unknown for gallery-dl
                            except Exception:
                                pass

            # Process the last pending file after the loop ends — but only if not cancelled
            if pending_file is not None and on_file:
                if cancel_check is None or not await cancel_check():
                    try:
                        await on_file(pending_file)
                    except Exception as exc:
                        logger.warning("[gallery_dl] progressive import error (last file): %s", exc)

        try:
            await asyncio.wait_for(
                asyncio.gather(_read_stdout(), proc.wait()),
                timeout=3600,
            )
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.error("[gallery_dl] timeout downloading: %s", url)
            return DownloadResult(
                status="failed",
                downloaded=downloaded,
                total=downloaded,
                error="download timeout after 3600s",
            )

        # Check if download was cancelled (covers both the break-from-loop path and
        # the race where SIGTERM was sent externally before _read_stdout detected it)
        if cancel_check is not None and await cancel_check():
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.info("[gallery_dl] cancelled: %s (files downloaded before cancel=%d)", url, downloaded)
            return DownloadResult(status="cancelled", downloaded=downloaded, total=downloaded)

        stderr_bytes = await proc.stderr.read() if proc.stderr else b""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            err = stderr_text[:500]
            logger.error("[gallery_dl] non-zero exit:\n%s", stderr_text)
            if downloaded > 0:
                # Some files were downloaded before the error — treat as partial success
                logger.warning(
                    "[gallery_dl] %d file(s) downloaded before failure — returning partial", downloaded
                )
                return DownloadResult(
                    status="partial",
                    downloaded=downloaded,
                    total=downloaded,
                    error=err,
                )
            return DownloadResult(
                status="failed",
                downloaded=downloaded,
                total=downloaded,
                error=err,
            )

        logger.info("[gallery_dl] done: %s (files=%d)", url, downloaded)
        return DownloadResult(
            status="done",
            downloaded=downloaded,
            total=downloaded,
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

                source_id = dest_dir.name
                for field in cfg.source_id_fields:
                    val = raw.get(field)
                    if val:
                        source_id = str(val)
                        break

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
