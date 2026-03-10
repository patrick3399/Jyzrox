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
from plugins.models import DownloadResult, FieldDef, GalleryMetadata, PluginMeta

logger = logging.getLogger(__name__)

_FILE_PATH_RE = re.compile(r"/data/")
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|avif|heic|mp4|webm)$", re.IGNORECASE)
_PROGRESS_EVERY_N = 5
_PROGRESS_EVERY_S = 10.0


def _source_to_extractor(source: str) -> str:
    """Map our source name to gallery-dl extractor name."""
    mapping = {
        "twitter": "twitter",
        "instagram": "instagram",
        "danbooru": "danbooru",
        "kemono": "kemono",
        "gelbooru": "gelbooru",
        "sankaku": "sankakucomplex",
    }
    return mapping.get(source, source)


async def _build_gallery_dl_config(credentials: dict) -> None:
    """Write source-specific credentials into the gallery-dl config file.

    Args:
        credentials: Dict mapping source name -> credential value string.
                     e.g. {"ehentai": '{"ipb_member_id": ...}', "pixiv": "token..."}
    """
    config: dict = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
            "directory": [],
        },
    }

    # EH cookies
    eh_cred = credentials.get("ehentai")
    if eh_cred:
        try:
            cookies = json.loads(eh_cred)
            config["extractor"]["exhentai"] = {"cookies": cookies}
            config["extractor"]["e-hentai"] = {"cookies": cookies}
        except (json.JSONDecodeError, TypeError):
            logger.warning("[gallery_dl] invalid EH cookie JSON, skipping")

    # Pixiv refresh token
    pixiv_token = credentials.get("pixiv")
    if pixiv_token:
        config["extractor"]["pixiv"] = {"refresh-token": pixiv_token}

    # Generic cookie credentials (twitter, instagram, etc.)
    for src, cred_val in credentials.items():
        if src in ("ehentai", "pixiv") or not cred_val:
            continue
        try:
            cookie_dict = json.loads(cred_val)
            extractor_name = _source_to_extractor(src)
            config["extractor"][extractor_name] = {"cookies": cookie_dict}
        except (json.JSONDecodeError, TypeError):
            logger.warning("[gallery_dl] invalid cookie JSON for source %s, skipping", src)

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
        url_patterns=[],  # handles everything — it is the fallback
        credential_schema=[],
        concurrency=1,
    )

    async def can_handle(self, url: str) -> bool:
        """Always returns True — gallery-dl is the universal fallback."""
        return True

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Run gallery-dl as a subprocess and stream progress."""
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
            url,
        ]

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

        async def _read_stdout() -> None:
            nonlocal downloaded, last_progress_update
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if _FILE_PATH_RE.search(line) or _IMAGE_EXT_RE.search(line):
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

        stderr_bytes = await proc.stderr.read() if proc.stderr else b""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            err = stderr_text[:500]
            logger.error("[gallery_dl] non-zero exit:\n%s", stderr_text)
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

    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        """Read the first *.json file gallery-dl wrote and return GalleryMetadata."""
        for meta_file in sorted(dest_dir.rglob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
                tags = raw.get("tags", [])
                rating = raw.get("rating")
                if rating and isinstance(tags, list):
                    tags = list(tags)  # don't mutate original
                    tags.append(f"rating:{rating}")
                return GalleryMetadata(
                    source=raw.get("category", "gallery_dl"),
                    source_id=str(
                        raw.get("gallery_id") or raw.get("tweet_id") or raw.get("id") or dest_dir.name
                    ),
                    title=raw.get("title") or raw.get("description") or dest_dir.name,
                    tags=tags,
                    pages=raw.get("count", 0),
                    uploader=raw.get("uploader") or raw.get("artist") or "",
                )
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                logger.warning("[gallery_dl] failed to read metadata %s: %s", meta_file, exc)
                continue
        return None
