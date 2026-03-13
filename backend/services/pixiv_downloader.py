"""
Native Pixiv downloader using PixivClient.

Replaces gallery-dl for Pixiv sources. Handles single illustrations
(including multi-page manga) and bulk user-works downloads.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from core.redis_client import get_typed_download_delay
from services.pixiv_client import PixivClient

logger = logging.getLogger(__name__)


async def download_pixiv_illust(
    illust_id: int,
    refresh_token: str,
    output_dir: Path,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    pause_check: Callable[[], Awaitable[bool]] | None = None,
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
        try:
            detail = await client.illust_detail(illust_id)
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

                filename = f"{i + 1:04d}.{ext}"
                (output_dir / filename).write_bytes(image_bytes)

                downloaded += 1
                if on_progress:
                    await on_progress(downloaded, total)

                # Small polite delay between pages
                if i < total - 1:
                    await asyncio.sleep(await get_typed_download_delay("pixiv", "page", 500))

            except Exception as exc:
                logger.error(
                    "Failed to download page %d of illust %d: %s", i + 1, illust_id, exc
                )
                failed_pages.append(i + 1)

        # Write metadata.json compatible with import_job
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

                posted_ts = int(
                    _dt.fromisoformat(create_date.replace("Z", "+00:00")).timestamp()
                )
            except (ValueError, TypeError):
                pass

        metadata = {
            "title": detail.get("title", f"pixiv_{illust_id}"),
            "category": "pixiv",
            "id": str(illust_id),
            "uploader": user.get("name", ""),
            "posted": posted_ts,
            "tags": tag_list,
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


async def download_pixiv_user_works(
    user_id: int,
    refresh_token: str,
    output_dir: Path,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    pause_check: Callable[[], Awaitable[bool]] | None = None,
    max_illusts: int = 0,
) -> dict:
    """
    Download all works by a Pixiv user.

    Each illustration is placed in its own subdirectory:
    ``{output_dir}/{illust_id}/``

    Args:
        user_id: Pixiv user ID
        refresh_token: Pixiv OAuth refresh token
        output_dir: Base directory (each illust gets a subdirectory)
        on_progress: Callback(downloaded_illusts, total_illusts)
        cancel_check: Callback() -> True if cancelled
        max_illusts: Max number of illustrations to download (0 = all)

    Returns:
        {"status": "done"|"cancelled"|"failed", "downloaded": int,
         "total": int, "failed": list[int]}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    async with PixivClient(refresh_token) as client:
        # Paginate through the user's illustrations to build the full list
        all_illusts: list[dict] = []
        offset = 0

        while True:
            if cancel_check and await cancel_check():
                return {
                    "status": "cancelled",
                    "downloaded": 0,
                    "total": len(all_illusts),
                    "failed": [],
                }

            try:
                data = await client.user_illusts(user_id, offset=offset)
            except Exception as exc:
                logger.error("Failed to fetch user %d illusts at offset %d: %s", user_id, offset, exc)
                break

            illusts = data.get("illusts", [])
            if not illusts:
                break

            all_illusts.extend(illusts)

            if max_illusts and len(all_illusts) >= max_illusts:
                all_illusts = all_illusts[:max_illusts]
                break

            next_offset = data.get("next_offset")
            if next_offset is None:
                break
            offset = next_offset

            await asyncio.sleep(await get_typed_download_delay("pixiv", "pagination", 1000))  # Rate limit between pages

        total = len(all_illusts)
        if total == 0:
            return {"status": "done", "downloaded": 0, "total": 0, "failed": []}

        downloaded = 0
        failed: list[int] = []

        for illust in all_illusts:
            if cancel_check and await cancel_check():
                return {
                    "status": "cancelled",
                    "downloaded": downloaded,
                    "total": total,
                    "failed": failed,
                }

            # Soft-pause: wait while paused
            while pause_check and await pause_check():
                if cancel_check and await cancel_check():
                    return {
                        "status": "cancelled",
                        "downloaded": downloaded,
                        "total": total,
                        "failed": failed,
                    }
                await asyncio.sleep(0.5)

            illust_id = illust.get("id")
            if not illust_id:
                continue

            illust_dir = output_dir / str(illust_id)
            try:
                result = await download_pixiv_illust(
                    illust_id=illust_id,
                    refresh_token=refresh_token,
                    output_dir=illust_dir,
                    cancel_check=cancel_check,
                    pause_check=pause_check,
                )

                if result["status"] == "done":
                    downloaded += 1
                elif result["status"] == "cancelled":
                    return {
                        "status": "cancelled",
                        "downloaded": downloaded,
                        "total": total,
                        "failed": failed,
                    }
                else:
                    failed.append(illust_id)

                if on_progress:
                    await on_progress(downloaded, total)

                await asyncio.sleep(await get_typed_download_delay("pixiv", "illust", 2000))  # Rate limit between illustrations

            except Exception as exc:
                logger.error("Failed to download illust %d: %s", illust_id, exc)
                failed.append(illust_id)

    final_status: str
    if downloaded == 0 and failed:
        final_status = "failed"
    else:
        final_status = "done"

    return {
        "status": final_status,
        "downloaded": downloaded,
        "total": total,
        "failed": failed,
    }
