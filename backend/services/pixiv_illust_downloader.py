"""Single-illustration Pixiv download (multi-page aware) with rate-limit handling."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from core.redis_client import get_typed_download_delay
from services.pixiv_client import PixivClient, PixivRateLimitError

logger = logging.getLogger(__name__)

# A throttled call is retried after the shared cooldown (services.pixiv_client)
# has run out; this many throttled attempts in a row end the download.
_RATE_LIMIT_ATTEMPTS = 4


async def _wait_out_rate_limit(retry_after: float, cancel_check: Callable[[], Awaitable[bool]] | None) -> bool:
    """Sleep through the cooldown in short slices; False when cancelled meanwhile."""
    remaining = retry_after
    while remaining > 0:
        if cancel_check and await cancel_check():
            return False
        step = min(remaining, 1.0)
        await asyncio.sleep(step)
        remaining -= step
    return not (cancel_check and await cancel_check())


async def download_pixiv_illust(
    illust_id: int,
    refresh_token: str,
    output_dir: Path,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    pause_check: Callable[[], Awaitable[bool]] | None = None,
    on_file: Callable[[Path], Awaitable[None]] | None = None,
    filename_prefix: str | None = None,
) -> dict:
    """
    Download a single Pixiv illustration (including multi-page manga).

    Args:
        illust_id: Pixiv illustration ID
        refresh_token: Pixiv OAuth refresh token
        output_dir: Directory to save images and metadata
        on_progress: Callback(downloaded, total) for progress updates
        cancel_check: Callback() -> True if download should be cancelled

    Returns:
        {"status": "done"|"cancelled"|"failed", "downloaded": int, "total": int,
         "failed_pages": list[int], "error": str | None}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    async with PixivClient(refresh_token) as client:
        # Get illustration detail (already normalised by PixivClient)
        detail = None
        try:
            for attempt in range(_RATE_LIMIT_ATTEMPTS):
                try:
                    detail = await client.illust_detail(illust_id)
                    break
                except PixivRateLimitError as limited:
                    if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                        raise
                    logger.warning("Pixiv rate limit on illust %d, waiting %.0fs", illust_id, limited.retry_after)
                    if not await _wait_out_rate_limit(limited.retry_after, cancel_check):
                        return {"status": "cancelled", "downloaded": 0, "total": 0, "failed_pages": []}
        except PixivRateLimitError as exc:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": 0,
                "failed_pages": [],
                "error": str(exc),
                "rate_limited": True,
            }
        except ValueError as exc:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": 0,
                "failed_pages": [],
                "error": str(exc),
            }
        except PermissionError as exc:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": 0,
                "failed_pages": [],
                "error": str(exc),
            }

        if not detail:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": 0,
                "failed_pages": [],
                "error": "Illustration not found",
            }

        # Collect image URLs.
        # For single-page illusts, image_urls.original is set by _normalize_illust.
        # For multi-page illusts, meta_pages is a list of
        # {"image_urls": {"original": ..., ...}} dicts, also set by _normalize_illust.
        page_count = detail.get("page_count", 1)
        image_urls: list[str] = []

        if page_count == 1:
            original = detail.get("image_urls", {}).get("original", "")
            if original:
                image_urls.append(original)
        else:
            # meta_pages is already normalized by PixivClient._normalize_illust
            # Each entry: {"image_urls": {"square_medium": ..., "medium": ..., "large": ..., "original": ...}}
            meta_pages = detail.get("meta_pages") or []
            for mp in meta_pages:
                original = mp.get("image_urls", {}).get("original", "")
                if original:
                    image_urls.append(original)

            # Fallback: use the single normalised original if meta_pages empty
            if not image_urls:
                original = detail.get("image_urls", {}).get("original", "")
                if original:
                    image_urls.append(original)

        total = len(image_urls)
        if total == 0:
            return {
                "status": "failed",
                "downloaded": 0,
                "total": 0,
                "failed_pages": [],
                "error": "No image URLs found",
            }

        if on_progress:
            await on_progress(0, total)

        downloaded = 0
        failed_pages: list[int] = []

        for i, url in enumerate(image_urls):
            # Check cancellation before each page
            if cancel_check and await cancel_check():
                return {
                    "status": "cancelled",
                    "downloaded": downloaded,
                    "total": total,
                    "failed_pages": failed_pages,
                }

            # Soft-pause: wait while paused
            while pause_check and await pause_check():
                if cancel_check and await cancel_check():
                    return {
                        "status": "cancelled",
                        "downloaded": downloaded,
                        "total": total,
                        "failed_pages": failed_pages,
                    }
                await asyncio.sleep(0.5)

            try:
                image_bytes, media_type = await client.download_image(url)

                # Determine extension from URL, then fall back to media_type
                ext = url.rsplit(".", 1)[-1].split("?")[0].lower() if "." in url else "jpg"
                if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                    ext_map = {
                        "image/jpeg": "jpg",
                        "image/png": "png",
                        "image/gif": "gif",
                        "image/webp": "webp",
                    }
                    ext = ext_map.get(media_type, "jpg")

                # Normalise jpeg -> jpg
                if ext == "jpeg":
                    ext = "jpg"

                filename = f"{filename_prefix}_p{i + 1:04d}.{ext}" if filename_prefix else f"{i + 1:04d}.{ext}"
                (output_dir / filename).write_bytes(image_bytes)
                if on_file is not None:
                    await on_file(output_dir / filename)

                downloaded += 1
                if on_progress:
                    await on_progress(downloaded, total)

                # Small polite delay between pages
                if i < total - 1:
                    await asyncio.sleep(await get_typed_download_delay("pixiv", "page", 500))

            except Exception as exc:
                logger.error("Failed to download page %d of illust %d: %s", i + 1, illust_id, exc)
                failed_pages.append(i + 1)

        # Write metadata.json compatible with import_job
        from plugins.builtin.pixiv._tags import process_pixiv_tags

        tag_list, tag_translations_data = process_pixiv_tags(detail)

        user = detail.get("user", {})
        posted_ts = 0
        create_date = detail.get("create_date", "")
        if create_date:
            try:
                from datetime import datetime as _dt

                posted_ts = int(_dt.fromisoformat(create_date.replace("Z", "+00:00")).timestamp())
            except ValueError, TypeError:
                pass

        metadata = {
            "title": detail.get("title", f"pixiv_{illust_id}"),
            "category": "pixiv",
            "id": str(illust_id),
            "uploader": user.get("name", ""),
            "posted": posted_ts,
            "tags": tag_list,
            "tag_translations": tag_translations_data,
            "page_count": page_count,
            "pixiv_user_id": user.get("id"),
            "pixiv_illust_type": detail.get("type", "illust"),
            "total_bookmarks": detail.get("total_bookmarks", 0),
            "total_view": detail.get("total_view", 0),
        }

        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    status: str
    if downloaded == 0:
        status = "failed"
    elif failed_pages:
        status = "done"  # partial success still treated as done
    else:
        status = "done"

    return {
        "status": status,
        "downloaded": downloaded,
        "total": total,
        "failed_pages": failed_pages,
        "error": None,
    }
