"""Native Pixiv Fanbox downloader.

Fanbox post selection is performed in Jyzrox instead of being delegated to a
global gallery-dl configuration.  This makes free/paid selection a property of
the request or subscription while the FANBOXSESSID credential stays global.
"""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from core.redis_client import get_typed_download_delay
from core.version import __version__
from plugins.base import SourcePlugin
from plugins.builtin.fanbox.policy import FanboxDownloadPolicy, fanbox_policy_from_options
from plugins.models import (
    CredentialFlow,
    CredentialStatus,
    DiscoveredWorks,
    DownloadResult,
    FieldDef,
    GalleryImportData,
    GalleryMetadata,
    NewWork,
    PluginMeta,
    SiteInfo,
)
from services.media_formats import IMAGE_EXTENSIONS as _IMAGE_EXTS
from services.media_formats import VIDEO_EXTENSIONS as _VIDEO_EXTS

logger = logging.getLogger(__name__)

_POST_RE = re.compile(r"(?:https?://)?(?:(?:www\.)?fanbox\.cc/@[\w-]+/|[\w-]+\.fanbox\.cc/)posts/(\d+)", re.I)
_CREATOR_RE = re.compile(r"(?:https?://)?(?:([\w-]+)\.fanbox\.cc|(?:www\.)?fanbox\.cc/@([\w-]+))/?$", re.I)


def _cookies(credentials: dict | str | None) -> dict[str, str]:
    if isinstance(credentials, str):
        if not credentials.strip():
            return {}
        try:
            parsed = json.loads(credentials)
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict):
            # Accept a browser-style single cookie value as a convenience for
            # the dedicated Fanbox credential flow.
            return {"FANBOXSESSID": credentials.strip()}
        credentials = parsed
    if not isinstance(credentials, dict):
        return {}
    # The credential form posts the `fanboxsessid` field declared by
    # credential_flows(); the cookie itself is upper-case.
    if credentials.get("fanboxsessid"):
        return {"FANBOXSESSID": str(credentials["fanboxsessid"])}
    raw = credentials.get("cookies", credentials)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _extension(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }.get((content_type or "").split(";", 1)[0].lower(), ".bin")


def _media_urls(post: dict, policy: FanboxDownloadPolicy) -> list[str]:
    """Extract direct media URLs from a Fanbox post body in display order."""
    body = post.get("body") or {}
    urls: list[str] = []
    if policy.include_images and post.get("coverImageUrl"):
        urls.append(str(post["coverImageUrl"]))
    for key in ("images", "imageMap"):
        values = body.get(key, {})
        values = values.values() if isinstance(values, dict) else values
        if policy.include_images and isinstance(values, list | tuple | type({}.values())):
            for item in values:
                if isinstance(item, dict) and item.get("originalUrl"):
                    urls.append(str(item["originalUrl"]))
    for key in ("files", "fileMap"):
        values = body.get(key, {})
        values = values.values() if isinstance(values, dict) else values
        if not hasattr(values, "__iter__"):
            continue
        for item in values:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            url = str(item["url"])
            suffix = Path(urlparse(url).path).suffix.lower()
            allowed = (
                (suffix in _VIDEO_EXTS and policy.include_videos)
                or (suffix in _IMAGE_EXTS and policy.include_images)
                or (policy.include_files and suffix not in _VIDEO_EXTS)
            )
            if allowed:
                urls.append(url)
    # Keep ordering stable while avoiding cover/image duplicates.
    return list(dict.fromkeys(urls))


class FanboxSourcePlugin(SourcePlugin):
    """Download individual Fanbox posts into one Jyzrox gallery."""

    meta = PluginMeta(
        name="Pixiv Fanbox",
        source_id="fanbox",
        version=__version__,
        description="Fanbox post downloader with per-job free/paid selection",
        url_patterns=["fanbox.cc"],
        credential_schema=[
            FieldDef(name="fanboxsessid", label="FANBOXSESSID Cookie", field_type="password", required=False)
        ],
        supported_sites=[
            SiteInfo(domain="fanbox.cc", name="Pixiv Fanbox", source_id="fanbox", category="art", has_tags=True)
        ],
        concurrency=1,
        semaphore_key="fanbox",
    )

    async def can_handle(self, url: str) -> bool:
        return bool(_POST_RE.search(url))

    @staticmethod
    def creator_id_from_url(url: str) -> str | None:
        match = _CREATOR_RE.search(url.rstrip("/"))
        return (match.group(1) or match.group(2)) if match else None

    async def discover_posts(
        self,
        creator_url: str,
        last_known: str | None,
        policy: FanboxDownloadPolicy,
        credentials: dict | str | None,
    ) -> tuple[list[NewWork], str | None]:
        """List a creator's matching posts newest-first.

        The returned boundary is independent of the policy so a free-only
        subscription can advance past paid posts without re-enumerating them on
        every schedule. A manual force re-scan intentionally passes no boundary.
        """
        creator_id = self.creator_id_from_url(creator_url)
        if not creator_id:
            raise ValueError("Fanbox subscription requires a creator URL")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.fanbox.cc/",
            "User-Agent": "Mozilla/5.0",
        }
        works: list[NewWork] = []
        latest_id: str | None = None
        async with httpx.AsyncClient(
            headers=headers, cookies=_cookies(credentials), follow_redirects=True, timeout=45
        ) as client:
            response = await client.get("https://api.fanbox.cc/post.paginateCreator", params={"creatorId": creator_id})
            response.raise_for_status()
            pages = response.json().get("body")
            if not isinstance(pages, list):
                return works, latest_id
            reached_boundary = False
            for page_url in pages:
                response = await client.get(str(page_url))
                response.raise_for_status()
                posts = response.json().get("body")
                if not isinstance(posts, list):
                    continue
                for item in posts:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    post_id = str(item["id"])
                    latest_id = latest_id or post_id
                    if last_known and post_id == last_known:
                        reached_boundary = True
                        break
                    fee = int(item.get("feeRequired") or 0)
                    if policy.includes_fee(fee):
                        posted_at = None
                        try:
                            posted_at = datetime.fromisoformat(
                                str(item.get("publishedDatetime", "")).replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                        works.append(
                            NewWork(
                                url=f"https://www.fanbox.cc/@{creator_id}/posts/{post_id}",
                                title=str(item.get("title") or ""),
                                source_id=post_id,
                                thumbnail_url=item.get("coverImageUrl"),
                                posted_at=posted_at,
                            )
                        )
                if reached_boundary:
                    break
                await asyncio.sleep(await get_typed_download_delay("fanbox", "pagination", 1000))
        return works, latest_id

    def subscription_identity(self, url: str) -> str | None:
        return self.creator_id_from_url(url)

    async def discover_new_works(
        self,
        url: str,
        last_known: str | None,
        options: dict,
        credentials: dict | str | None,
    ) -> DiscoveredWorks:
        from plugins.builtin.fanbox.policy import fanbox_policy_from_options

        policy = fanbox_policy_from_options(options if isinstance(options, dict) else {})
        # Without a logged-in session, an "all accessible" creator sync means
        # public/free content only. Avoid enqueueing a noisy job for every paid
        # post merely to discover that the account has no entitlement.
        selection_policy = policy
        if not credentials and policy.content != "free_only":
            selection_policy = policy.model_copy(update={"content": "free_only"})
        works, latest_id = await self.discover_posts(url, last_known, selection_policy, credentials)
        return DiscoveredWorks(
            works=works,
            latest_id=latest_id,
            job_options={"fanbox": policy.model_dump(mode="json")},
        )

    def requires_credentials(self) -> bool:
        # Free posts remain useful without a logged-in account.
        return False

    def resolve_output_dir(self, url: str, base_path: Path, job_id: str | None = None) -> Path:
        match = _POST_RE.search(url)
        return base_path / "fanbox" / (match.group(1) if match else "unknown")

    async def resolve_metadata(self, url: str, credentials: dict | str | None) -> GalleryImportData | None:
        return None

    def credential_flows(self) -> list[CredentialFlow]:
        return [
            CredentialFlow(
                flow_type="fields",
                fields=[
                    FieldDef(
                        name="fanboxsessid",
                        label="FANBOXSESSID Cookie",
                        field_type="password",
                        required=False,
                        placeholder="Paste the FANBOXSESSID cookie value",
                    )
                ],
            )
        ]

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        cookies = _cookies(credentials)
        if not cookies.get("FANBOXSESSID"):
            return CredentialStatus(valid=False, error="FANBOXSESSID cookie is required for paid posts")
        return CredentialStatus(valid=True)

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
        pause_check: Callable[[], Awaitable[bool]] | None = None,
        on_file: Callable[[Path, str | None], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult:
        match = _POST_RE.search(url)
        if not match:
            return DownloadResult(
                status="failed", downloaded=0, total=0, error="Fanbox requires an individual post URL"
            )
        try:
            policy = fanbox_policy_from_options(options)
        except ValueError as exc:
            return DownloadResult(
                status="failed", downloaded=0, total=0, error=f"Invalid Fanbox download policy: {exc}"
            )

        post_id = match.group(1)
        dest_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.fanbox.cc/",
            "User-Agent": "Mozilla/5.0",
        }
        summary = {"policy": policy.model_dump(mode="json"), "skipped_policy": 0, "skipped_inaccessible": 0}
        diagnostic = (options or {}).get("diagnostic_ctx")
        if isinstance(diagnostic, dict):
            diagnostic["source_summary"] = summary

        async with httpx.AsyncClient(
            headers=headers, cookies=_cookies(credentials), follow_redirects=True, timeout=45
        ) as client:
            try:
                response = await client.get("https://api.fanbox.cc/post.info", params={"postId": post_id})
                if response.status_code in (401, 403):
                    summary["skipped_inaccessible"] = 1
                    return DownloadResult(status="done", downloaded=0, total=0)
                response.raise_for_status()
                post = response.json().get("body")
            except (httpx.HTTPError, ValueError) as exc:
                return DownloadResult(status="failed", downloaded=0, total=0, error=f"Fanbox post lookup failed: {exc}")
            if not isinstance(post, dict):
                return DownloadResult(status="failed", downloaded=0, total=0, error="Fanbox returned no post data")

            fee = int(post.get("feeRequired") or 0)
            if not policy.includes_fee(fee):
                summary["skipped_policy"] = 1
                return DownloadResult(status="done", downloaded=0, total=0)

            urls = _media_urls(post, policy)
            if on_progress:
                await on_progress(0, len(urls))
            downloaded = 0
            failed: list[int] = []
            metadata = {
                "category": "fanbox",
                "id": post_id,
                "gallery_id": post_id,
                "title": post.get("title") or f"fanbox_{post_id}",
                "uploader": post.get("creatorId") or "",
                "date": post.get("publishedDatetime"),
                "description": post.get("body", {}).get("text", "") if isinstance(post.get("body"), dict) else "",
                "fee_required": fee,
                "creator_id": post.get("creatorId"),
                "post_type": post.get("type"),
            }
            for index, media_url in enumerate(urls, start=1):
                if cancel_check and await cancel_check():
                    return DownloadResult(
                        status="cancelled", downloaded=downloaded, total=len(urls), failed_pages=failed
                    )
                while pause_check and await pause_check():
                    if cancel_check and await cancel_check():
                        return DownloadResult(
                            status="cancelled", downloaded=downloaded, total=len(urls), failed_pages=failed
                        )
                    await asyncio.sleep(0.5)
                try:
                    media = await client.get(media_url)
                    media.raise_for_status()
                    path = (
                        dest_dir / f"{post_id}_p{index:04d}{_extension(media_url, media.headers.get('content-type'))}"
                    )
                    path.write_bytes(media.content)
                    path.with_name(path.name + ".json").write_text(
                        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
                    )
                    downloaded += 1
                    if on_file:
                        await on_file(path, None)
                    if on_progress:
                        await on_progress(downloaded, len(urls))
                    if index < len(urls):
                        await asyncio.sleep(await get_typed_download_delay("fanbox", "page", 1000))
                except httpx.HTTPError as exc:
                    logger.warning("[fanbox] failed post=%s media=%d: %s", post_id, index, exc)
                    failed.append(index)
        return DownloadResult(
            status="partial" if failed and downloaded else "done",
            downloaded=downloaded,
            total=len(urls),
            failed_pages=failed,
        )

    def parse_import(self, dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        return parse_gallery_dl_import(dest_dir, raw_meta, fallback_source="fanbox")

    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        return None
