"""Pixiv native download plugin.

Handles pixiv.net artwork URLs and user profile URLs.
Delegates to services.pixiv_downloader so the import pipeline receives
standard metadata.json and numbered image files.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from plugins.base import SourcePlugin
from plugins.models import DownloadResult, FieldDef, GalleryMetadata, PluginMeta

logger = logging.getLogger(__name__)

# Matches: /artworks/12345  or  /i/12345  (mobile redirect)
_PIXIV_ART_RE = re.compile(r"pixiv\.net/(?:en/)?(?:artworks|i)/(\d+)")
# Matches: /users/12345
_PIXIV_USER_RE = re.compile(r"pixiv\.net/(?:en/)?users/(\d+)")


class PixivSourcePlugin(SourcePlugin):
    """SourcePlugin for Pixiv illustrations and user galleries."""

    meta = PluginMeta(
        name="Pixiv",
        source_id="pixiv",
        version="1.0.0",
        url_patterns=["pixiv.net"],
        credential_schema=[
            FieldDef(
                name="refresh_token",
                label="Refresh Token",
                field_type="password",
                required=True,
                placeholder="",
            ),
        ],
        concurrency=4,
    )

    async def can_handle(self, url: str) -> bool:
        return "pixiv.net" in url

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download a Pixiv artwork or user gallery."""
        from services.pixiv_downloader import download_pixiv_illust, download_pixiv_user_works

        # Extract refresh token from credentials (stored as plain string in DB)
        if isinstance(credentials, str):
            refresh_token = credentials
        elif isinstance(credentials, dict):
            refresh_token = credentials.get("refresh_token", "")
        else:
            return DownloadResult(
                status="failed",
                downloaded=0,
                total=0,
                error="No Pixiv credentials configured",
            )

        if not refresh_token:
            return DownloadResult(
                status="failed",
                downloaded=0,
                total=0,
                error="No Pixiv refresh token",
            )

        art_match = _PIXIV_ART_RE.search(url)
        user_match = _PIXIV_USER_RE.search(url)

        try:
            if art_match:
                illust_id = int(art_match.group(1))
                result = await download_pixiv_illust(
                    illust_id=illust_id,
                    refresh_token=refresh_token,
                    output_dir=dest_dir,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                )
            elif user_match:
                user_id = int(user_match.group(1))
                result = await download_pixiv_user_works(
                    user_id=user_id,
                    refresh_token=refresh_token,
                    output_dir=dest_dir,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                )
            else:
                return DownloadResult(
                    status="failed",
                    downloaded=0,
                    total=0,
                    error=f"Cannot parse Pixiv URL: {url}",
                )
        except PermissionError as exc:
            err = str(exc)
            logger.error("[pixiv] permission error: %s", err)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)
        except Exception as exc:
            err = f"Pixiv download failed: {exc}"
            logger.error("[pixiv] %s", err, exc_info=True)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)

        status = result.get("status", "failed")
        if status not in ("done", "cancelled", "failed"):
            status = "failed"

        return DownloadResult(
            status=status,  # type: ignore[arg-type]
            downloaded=result.get("downloaded", 0),
            total=result.get("total", 0),
            failed_pages=result.get("failed_pages", []),
            error=result.get("error"),
        )

    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        """Read metadata.json written by download_pixiv_illust."""
        meta_file = dest_dir / "metadata.json"
        if not meta_file.exists():
            return None
        try:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[pixiv] failed to read metadata.json: %s", exc)
            return None

        posted_at: datetime | None = None
        posted_raw = raw.get("posted")
        if posted_raw:
            try:
                posted_at = datetime.fromtimestamp(int(posted_raw), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        return GalleryMetadata(
            source="pixiv",
            source_id=str(raw.get("id", dest_dir.name)),
            title=raw.get("title") or dest_dir.name,
            tags=raw.get("tags", []),
            pages=0,  # determined from actual downloaded files by import_job
            uploader=raw.get("uploader", ""),
            posted_at=posted_at,
            extra={
                "pixiv_user_id": raw.get("pixiv_user_id"),
                "pixiv_illust_type": raw.get("pixiv_illust_type", "illust"),
                "total_bookmarks": raw.get("total_bookmarks", 0),
                "total_view": raw.get("total_view", 0),
            },
        )
