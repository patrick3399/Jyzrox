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
        description="Universal gallery-dl fallback downloader",
        url_patterns=[],  # handles everything — it is the fallback
        credential_schema=[],
        supported_sites=[
            SiteInfo(domain="twitter.com", source_id="twitter", name="Twitter/X", category="social", has_tags=True),
            SiteInfo(domain="x.com", source_id="twitter", name="Twitter/X", category="social", has_tags=True),
            SiteInfo(domain="danbooru.donmai.us", source_id="danbooru", name="Danbooru", category="booru", has_tags=True),
            SiteInfo(domain="gelbooru.com", source_id="gelbooru", name="Gelbooru", category="booru", has_tags=True),
            SiteInfo(domain="e621.net", source_id="e621", name="e621", category="booru", has_tags=True),
            SiteInfo(domain="yande.re", source_id="yandere", name="Yande.re", category="booru", has_tags=True),
            SiteInfo(domain="konachan.com", source_id="konachan", name="Konachan", category="booru", has_tags=True),
            SiteInfo(domain="rule34.xxx", source_id="rule34", name="Rule34", category="booru", has_tags=True),
            SiteInfo(domain="safebooru.org", source_id="safebooru", name="Safebooru", category="booru", has_tags=True),
            SiteInfo(domain="sankakucomplex.com", source_id="sankaku", name="Sankaku", category="booru", has_tags=True),
            SiteInfo(domain="deviantart.com", source_id="deviantart", name="DeviantArt", category="art", has_tags=True),
            SiteInfo(domain="artstation.com", source_id="artstation", name="ArtStation", category="art", has_tags=True),
            SiteInfo(domain="newgrounds.com", source_id="newgrounds", name="Newgrounds", category="art", has_tags=True),
            SiteInfo(domain="inkbunny.net", source_id="inkbunny", name="Inkbunny", category="art", has_tags=True),
            SiteInfo(domain="furaffinity.net", source_id="furaffinity", name="Fur Affinity", category="art", has_tags=True),
            SiteInfo(domain="nhentai.net", source_id="nhentai", name="nhentai", category="gallery", has_tags=True),
            SiteInfo(domain="hitomi.la", source_id="hitomi", name="Hitomi.la", category="gallery", has_tags=True),
            SiteInfo(domain="kemono.su", source_id="kemono", name="Kemono", category="gallery", has_tags=True),
            SiteInfo(domain="mangadex.org", source_id="mangadex", name="MangaDex", category="manga", has_tags=True),
            SiteInfo(domain="instagram.com", source_id="instagram", name="Instagram", category="social", has_tags=True),
            SiteInfo(domain="bsky.app", source_id="bluesky", name="Bluesky", category="social", has_tags=True),
            SiteInfo(domain="tumblr.com", source_id="tumblr", name="Tumblr", category="social", has_tags=True),
            SiteInfo(domain="reddit.com", source_id="reddit", name="Reddit", category="social", has_tags=True),
            SiteInfo(domain="facebook.com", source_id="facebook", name="Facebook", category="social", has_tags=False),
            SiteInfo(domain="civitai.com", source_id="civitai", name="Civitai", category="art", has_tags=True),
            SiteInfo(domain="imgur.com", source_id="imgur", name="Imgur", category="filehost", has_tags=False),
            SiteInfo(domain="bunkr.si", source_id="bunkr", name="Bunkr", category="filehost", has_tags=False),
            SiteInfo(domain="cyberdrop.me", source_id="cyberdrop", name="Cyberdrop", category="filehost", has_tags=False),
            SiteInfo(domain="catbox.moe", source_id="catbox", name="Catbox", category="filehost", has_tags=False),
        ],
        concurrency=1,
        semaphore_key="gallery_dl",
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
