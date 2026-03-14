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
from plugins.models import (
    CredentialFlow,
    CredentialStatus,
    DownloadResult,
    FieldDef,
    GalleryImportData,
    GalleryMetadata,
    NewWork,
    PluginMeta,
    SiteInfo,
)

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
        description="Pixiv artwork and user downloader",
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
        supported_sites=[
            SiteInfo(domain="pixiv.net", name="Pixiv", source_id="pixiv", category="art", has_tags=True),
        ],
        concurrency=4,
        semaphore_key="pixiv",
    )

    async def can_handle(self, url: str) -> bool:
        return "pixiv.net" in url

    async def resolve_metadata(
        self,
        url: str,
        credentials: dict | str | None,
    ) -> GalleryImportData | None:
        """Resolve Pixiv illustration metadata before download via API."""
        from services.pixiv_client import PixivClient

        # Extract refresh token
        if isinstance(credentials, str):
            refresh_token = credentials
        elif isinstance(credentials, dict):
            refresh_token = credentials.get("refresh_token", "")
        else:
            return None
        if not refresh_token:
            return None

        art_match = _PIXIV_ART_RE.search(url)
        if not art_match:
            # User works URLs don't have a single metadata to resolve
            return None

        illust_id = int(art_match.group(1))

        try:
            async with PixivClient(refresh_token) as client:
                detail = await client.illust_detail(illust_id)
        except Exception as exc:
            logger.warning("[pixiv] resolve_metadata failed: %s", exc)
            return None

        if not detail:
            return None

        # Build metadata dict in the same format as download_pixiv_illust writes
        tags = detail.get("tags", [])
        tag_list: list[str] = []
        for tag in tags:
            if isinstance(tag, dict):
                name = tag.get("name", "")
                if name:
                    tag_list.append(name)
                translated = tag.get("translated_name")
                if translated and translated != name:
                    tag_list.append(translated)
            elif isinstance(tag, str):
                tag_list.append(tag)

        user = detail.get("user", {})
        posted_ts = 0
        create_date = detail.get("create_date", "")
        if create_date:
            try:
                from datetime import datetime as _dt
                posted_ts = int(_dt.fromisoformat(create_date.replace("Z", "+00:00")).timestamp())
            except (ValueError, TypeError):
                pass

        metadata_dict = {
            "title": detail.get("title", f"pixiv_{illust_id}"),
            "category": "pixiv",
            "id": str(illust_id),
            "uploader": user.get("name", ""),
            "posted": posted_ts,
            "tags": tag_list,
            "page_count": detail.get("page_count", 1),
            "pixiv_user_id": user.get("id"),
            "pixiv_illust_type": detail.get("type", "illust"),
            "total_bookmarks": detail.get("total_bookmarks", 0),
            "total_view": detail.get("total_view", 0),
        }

        return self.parse_import(Path(f"/tmp/pixiv-{illust_id}"), metadata_dict)

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
        pause_check: Callable[[], Awaitable[bool]] | None = None,
        on_file: Callable[[Path], Awaitable[None]] | None = None,
        options: dict | None = None,
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
                    pause_check=pause_check,
                    on_file=on_file,
                )
            elif user_match:
                user_id = int(user_match.group(1))
                result = await download_pixiv_user_works(
                    user_id=user_id,
                    refresh_token=refresh_token,
                    output_dir=dest_dir,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                    pause_check=pause_check,
                    on_file=on_file,
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

    # ── Downloadable protocol methods ─────────────────────────────────

    def resolve_output_dir(self, url: str, base_path: Path) -> Path:
        """Determine output directory for Pixiv download."""
        art_match = _PIXIV_ART_RE.search(url)
        user_match = _PIXIV_USER_RE.search(url)
        if art_match:
            return base_path / "pixiv" / art_match.group(1)
        elif user_match:
            return base_path / "pixiv" / f"user_{user_match.group(1)}"
        return base_path / "pixiv" / "unknown"

    def requires_credentials(self) -> bool:
        """Pixiv always requires credentials."""
        return True

    # ── Parseable protocol methods ─────────────────────────────────────

    def parse_import(self, dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
        """Parse downloaded Pixiv gallery into structured import data."""
        from plugins.builtin.pixiv._metadata import parse_pixiv_import
        return parse_pixiv_import(dest_dir, raw_meta)

    # ── CredentialProvider protocol methods ───────────────────────────

    def credential_flows(self) -> list[CredentialFlow]:
        """Declare Pixiv credential flows: token + OAuth + cookie."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows
        return pixiv_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        """Verify Pixiv refresh token."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential
        return await verify_pixiv_credential(credentials)

    # ── Subscribable protocol methods ─────────────────────────────────

    async def check_new_works(
        self,
        artist_id: str,
        last_known: str | None,
        credentials: dict | None,
    ) -> list[NewWork]:
        """Check a Pixiv artist for new works since last_known."""
        from plugins.builtin.pixiv._subscribe import check_pixiv_new_works
        return await check_pixiv_new_works(artist_id, last_known, credentials)

    # ── Legacy SourcePlugin abstract method ───────────────────────────

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
