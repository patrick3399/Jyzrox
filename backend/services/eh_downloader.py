"""
Native E-Hentai gallery downloader.

Replaces gallery-dl for EH sources. Uses EhClient's showpage API
for fast image URL resolution + parallel downloads (default 3 concurrent).
Reuses Redis cache from browsing proxy for instant cache hits.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from core.config import settings
from core.redis_client import get_redis
from services import cache
from services.eh_client import EhClient, _detect_media_type

logger = logging.getLogger(__name__)


async def download_eh_gallery(
    gid: int,
    token: str,
    cookies: dict,
    use_ex: bool,
    output_dir: Path,
    concurrency: int = 3,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    cancel_key: str | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
) -> dict:
    """Download all images of an EH gallery using native EhClient.

    Args:
        gid: Gallery ID
        token: Gallery token (from URL)
        cookies: EH cookies dict
        use_ex: Whether to use ExHentai
        output_dir: Directory to save images
        concurrency: Number of parallel image downloads
        on_progress: Async callback(downloaded_count, total_pages)
        cancel_key: Redis key to check for cancellation (direct / legacy callers)
        cancel_check: Async callable that returns True when the download should
            be cancelled (plugin path; takes precedence over cancel_key)

    Returns:
        {"status": "done"|"cancelled"|"failed", "downloaded": int, "total": int, "failed_pages": list}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    async with EhClient(cookies, use_ex=use_ex) as client:
        # 1. Fetch metadata (check cache first)
        meta = await cache.get_gallery_cache(gid)
        if not meta:
            meta = await client.get_gallery_metadata(gid, token)
            await cache.set_gallery_cache(gid, meta)

        total_pages = meta.get("pages", 0)
        if total_pages == 0:
            return {"status": "failed", "downloaded": 0, "total": 0, "failed_pages": [], "error": "Gallery has 0 pages"}

        # 2. Fetch pTokens (check cache first)
        cached_tokens = await cache.get_imagelist_cache(gid)
        if cached_tokens and len(cached_tokens) >= total_pages:
            # Cache stores {str(page_num): ptoken}
            token_map = {int(k): v for k, v in cached_tokens.items()}
        else:
            token_map, _ = await client.get_image_tokens(gid, token, total_pages)
            # Cache for future use
            await cache.set_imagelist_cache(gid, {str(k): v for k, v in token_map.items()})

        if not token_map:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": total_pages,
                "failed_pages": list(range(1, total_pages + 1)),
                "error": "Failed to fetch image tokens",
            }

        # 3. Get showkey from first image page (one-time per gallery)
        first_page = min(token_map.keys())
        first_ptoken = token_map[first_page]
        showkey, _ = await client.get_showkey(gid, first_page, first_ptoken)

        # 4. Parallel download with semaphore
        sem = asyncio.Semaphore(concurrency)
        downloaded = 0
        failed_pages: list[int] = []
        lock = asyncio.Lock()

        async def _check_cancel() -> bool:
            # Prefer the injected cancel_check callable (plugin path); fall back
            # to the Redis cancel_key (direct / legacy callers).
            if cancel_check is not None:
                try:
                    return await cancel_check()
                except Exception:
                    return False
            if not cancel_key:
                return False
            try:
                val = await get_redis().get(cancel_key)
                return val is not None
            except Exception:
                return False

        async def _download_one(page_num: int, ptoken: str) -> None:
            nonlocal downloaded

            # Check cancellation before queuing
            if await _check_cancel():
                raise asyncio.CancelledError()

            # Check if file already exists (resume support)
            existing = list(output_dir.glob(f"{page_num:04d}.*"))
            if existing:
                async with lock:
                    downloaded += 1
                    if on_progress:
                        await on_progress(downloaded, total_pages)
                return

            async with sem:
                # Check cancellation again after acquiring semaphore
                if await _check_cancel():
                    raise asyncio.CancelledError()

                # Try cache first (image may have been proxied during browsing)
                cached_bytes = await cache.get_proxied_image(gid, page_num)
                if cached_bytes:
                    media_type = _detect_media_type(cached_bytes)
                    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
                    ext = ext_map.get(media_type, "jpg")
                    filepath = output_dir / f"{page_num:04d}.{ext}"
                    filepath.write_bytes(cached_bytes)
                    logger.debug("[eh_download] page %d: from cache (%d bytes)", page_num, len(cached_bytes))
                else:
                    # Download via showpage API
                    data, _media_type, ext = await client.download_image_with_retry(
                        showkey, gid, page_num, ptoken,
                        max_retries=settings.eh_download_max_retries,
                    )
                    filepath = output_dir / f"{page_num:04d}.{ext}"
                    filepath.write_bytes(data)
                    logger.debug("[eh_download] page %d: downloaded (%d bytes)", page_num, len(data))

                async with lock:
                    downloaded += 1
                    if on_progress:
                        await on_progress(downloaded, total_pages)

        # Launch all download tasks
        tasks = [_download_one(page_num, token_map[page_num]) for page_num in sorted(token_map.keys())]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            return {"status": "cancelled", "downloaded": downloaded, "total": total_pages, "failed_pages": []}

        # Process results
        sorted_pages = sorted(token_map.keys())
        for i, result in enumerate(results):
            page_num = sorted_pages[i]
            if isinstance(result, asyncio.CancelledError):
                return {"status": "cancelled", "downloaded": downloaded, "total": total_pages, "failed_pages": []}
            if isinstance(result, Exception):
                logger.error("[eh_download] page %d failed: %s", page_num, result)
                failed_pages.append(page_num)

        # 5. Write metadata.json (compatible with import_job's _extract_tags and _build_gallery)
        metadata_out = {
            "title": meta.get("title", ""),
            "title_jpn": meta.get("title_jpn", ""),
            "category": meta.get("category", ""),
            "uploader": meta.get("uploader", ""),
            "posted": meta.get("posted_at", 0),
            "tags": meta.get("tags", []),
            "gid": gid,
            "token": token,
        }
        (output_dir / "metadata.json").write_text(json.dumps(metadata_out, ensure_ascii=False, indent=2))

        status = "done" if not failed_pages else ("failed" if len(failed_pages) == total_pages else "done")
        return {
            "status": status,
            "downloaded": downloaded,
            "total": total_pages,
            "failed_pages": failed_pages,
        }
