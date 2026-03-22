"""E-Hentai / ExHentai SourcePlugin.

Delegates to services.eh_downloader.download_eh_gallery so that all existing
import pipeline code continues to work unchanged.
"""

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

_EH_URL_RE = re.compile(r"https?://(?:e-hentai|exhentai)\.org/g/(\d+)/([a-f0-9]+)")

class EhSourcePlugin(SourcePlugin):
    """SourcePlugin for E-Hentai and ExHentai galleries."""

    meta = PluginMeta(
        name="E-Hentai",
        source_id="ehentai",
        version="1.0.0",
        description="E-Hentai / ExHentai gallery downloader",
        url_patterns=["e-hentai.org", "exhentai.org"],
        credential_schema=[
            FieldDef(
                name="ipb_member_id",
                field_type="text",
                label="ipb_member_id",
                required=True,
                placeholder="12345",
            ),
            FieldDef(
                name="ipb_pass_hash",
                field_type="password",
                label="ipb_pass_hash",
                required=True,
                placeholder="",
            ),
            FieldDef(
                name="sk",
                field_type="password",
                label="sk",
                required=False,
                placeholder="",
            ),
            FieldDef(
                name="igneous",
                field_type="password",
                label="igneous (ExHentai)",
                required=False,
                placeholder="",
            ),
        ],
        supported_sites=[
            SiteInfo(domain="e-hentai.org", name="E-Hentai", source_id="ehentai", category="gallery", has_tags=True),
            SiteInfo(domain="exhentai.org", name="ExHentai", source_id="ehentai", category="gallery", has_tags=True),
        ],
        concurrency=3,
        semaphore_key="ehentai",
    )

    async def can_handle(self, url: str) -> bool:
        return "e-hentai.org" in url or "exhentai.org" in url

    async def resolve_metadata(
        self,
        url: str,
        credentials: dict | str | None,
    ) -> GalleryImportData | None:
        """Resolve EH gallery metadata before download via API."""
        from services.eh_client import _GALLERY_URL_RE as EH_GALLERY_URL_RE

        m = EH_GALLERY_URL_RE.search(url)
        if not m:
            return None

        gid = int(m.group(1))
        token = m.group(2)

        # Parse credentials
        if not credentials:
            cookies: dict = {}
        elif isinstance(credentials, str):
            try:
                cookies = json.loads(credentials)
            except json.JSONDecodeError, TypeError:
                return None
        else:
            cookies = credentials

        from core.config import settings
        from core.redis_client import get_redis
        from services import cache
        from services.eh_client import EhClient

        redis = get_redis()
        pref = await redis.get("setting:eh_use_ex")
        if pref is not None:
            use_ex = pref == b"1"
        else:
            use_ex = settings.eh_use_ex or bool(cookies.get("igneous"))
        if not cookies:
            use_ex = False

        try:
            async with EhClient(cookies, use_ex=use_ex) as client:
                meta = await cache.get_gallery_cache(gid)
                if not meta:
                    meta = await client.get_gallery_metadata(gid, token)
                    await cache.set_gallery_cache(gid, meta)
        except Exception as exc:
            logger.warning("[ehentai] resolve_metadata failed: %s", exc)
            return None

        # Build metadata dict in the same format as download_eh_gallery writes
        metadata_dict = {
            "category": "ehentai",
            "gallery_category": meta.get("category", ""),
            "title": meta.get("title", ""),
            "title_jpn": meta.get("title_jpn", ""),
            "uploader": meta.get("uploader", ""),
            "posted": meta.get("posted_at", 0),
            "tags": meta.get("tags", []),
            "gallery_id": gid,
            "gid": gid,
            "token": token,
        }

        # Reuse existing parse_import to build GalleryImportData
        return self.parse_import(Path(f"/tmp/eh-{gid}"), metadata_dict)

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
        """Download an EH gallery using the native EhClient downloader."""
        from core.config import settings
        from services.eh_client import _GALLERY_URL_RE as EH_GALLERY_URL_RE
        from services.eh_downloader import download_eh_gallery

        m = EH_GALLERY_URL_RE.search(url)
        if not m:
            err = f"Cannot parse EH gallery URL: {url}"
            logger.error("[ehentai] %s", err)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)

        gid = int(m.group(1))
        token = m.group(2)

        # Accept both a JSON-string credential (from worker) and a pre-parsed dict.
        # When no credentials are provided, fall back to anonymous (empty cookies).
        if not credentials:
            cookies: dict = {}
        elif isinstance(credentials, str):
            try:
                cookies = json.loads(credentials)
            except json.JSONDecodeError, TypeError:
                err = "E-Hentai credentials JSON is malformed"
                return DownloadResult(status="failed", downloaded=0, total=0, error=err)
        else:
            # credentials passed as dict (e.g. from direct call)
            cookies = credentials

        # Determine use_ex: Redis setting → config → igneous cookie → URL domain.
        # Anonymous downloads must use e-hentai.org, not exhentai.
        from core.redis_client import get_redis
        redis = get_redis()
        pref = await redis.get("setting:eh_use_ex")
        if pref is not None:
            use_ex = pref == b"1"
        else:
            use_ex = settings.eh_use_ex or bool(cookies.get("igneous"))

        if not cookies:
            use_ex = False  # anonymous access only works on e-hentai.org

        # Wrap on_progress to match signature expected by download_eh_gallery
        async def _progress(downloaded: int, total_pages: int) -> None:
            if on_progress is not None:
                await on_progress(downloaded, total_pages)

        from core.redis_client import get_image_concurrency
        image_concurrency = await get_image_concurrency("ehentai", settings.eh_download_concurrency)

        try:
            result = await download_eh_gallery(
                gid=gid,
                token=token,
                cookies=cookies,
                use_ex=use_ex,
                output_dir=dest_dir,
                concurrency=image_concurrency,
                on_progress=_progress,
                cancel_check=cancel_check,
                pause_check=pause_check,
                on_file=on_file,
            )
        except PermissionError as exc:
            err = str(exc)
            logger.error("[ehentai] permission error: %s", err)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)
        except ValueError as exc:
            err = str(exc)
            logger.warning("[ehentai] %s", err)
            return DownloadResult(status="failed", downloaded=0, total=0, error=err)
        except Exception as exc:
            err = f"EH download failed: {exc}"
            logger.error("[ehentai] %s", err, exc_info=True)
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
        """Read metadata.json written by download_eh_gallery."""
        meta_file = dest_dir / "metadata.json"
        if not meta_file.exists():
            return None
        try:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[ehentai] failed to read metadata.json: %s", exc)
            return None

        posted_at: datetime | None = None
        posted_raw = raw.get("posted")
        if posted_raw:
            try:
                posted_at = datetime.fromtimestamp(int(posted_raw), tz=timezone.utc)
            except ValueError, TypeError, OSError:
                pass

        return GalleryMetadata(
            source="ehentai",
            source_id=str(raw.get("gid", dest_dir.name)),
            title=raw.get("title") or raw.get("title_jpn") or dest_dir.name,
            tags=raw.get("tags", []),
            pages=0,  # will be determined from actual downloaded files
            uploader=raw.get("uploader") or "",
            posted_at=posted_at,
            extra={
                "title_jpn": raw.get("title_jpn", ""),
                "category": raw.get("category", ""),
                "token": raw.get("token", ""),
            },
        )

    # ------------------------------------------------------------------
    # Downloadable protocol methods
    # ------------------------------------------------------------------

    def resolve_output_dir(self, url: str, base_path: Path) -> Path:
        """Determine output directory for an EH gallery download."""
        m = _EH_URL_RE.search(url)
        if m:
            return base_path / "ehentai" / m.group(1)
        return base_path / "ehentai" / "unknown"

    def requires_credentials(self) -> bool:
        """E-Hentai supports anonymous downloads (with limited bandwidth)."""
        return False

    # ------------------------------------------------------------------
    # Parseable protocol method
    # ------------------------------------------------------------------

    def parse_import(self, dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
        """Parse a downloaded EH gallery directory into GalleryImportData."""
        from plugins.builtin.ehentai._metadata import parse_eh_import
        return parse_eh_import(dest_dir, raw_meta)

    # ------------------------------------------------------------------
    # CredentialProvider protocol methods
    # ------------------------------------------------------------------

    def credential_flows(self) -> list[CredentialFlow]:
        """Declare EH credential flows: cookie fields + login."""
        from plugins.builtin.ehentai._credentials import eh_credential_flows
        return eh_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        """Verify EH cookies by testing access against the EhClient."""
        from plugins.builtin.ehentai._credentials import verify_eh_credential
        return await verify_eh_credential(credentials)

    # ------------------------------------------------------------------
    # Subscribable protocol method
    # ------------------------------------------------------------------

    async def check_new_works(
        self, artist_id: str, last_known: str | None, credentials: dict | None,
    ) -> list[NewWork]:
        from plugins.builtin.ehentai._subscribe import check_eh_new_works
        return await check_eh_new_works(artist_id, last_known, credentials)
