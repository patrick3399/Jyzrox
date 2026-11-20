"""
Native Pixiv downloader using PixivClient.

Replaces gallery-dl for Pixiv sources. Handles single illustrations
(including multi-page manga) and bulk user-works downloads.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from core.redis_client import get_typed_download_delay
from services.pixiv_client import PixivClient, PixivRateLimitError
from services.pixiv_illust_downloader import (
    _RATE_LIMIT_ATTEMPTS,
    _wait_out_rate_limit,
    download_pixiv_illust,
)

logger = logging.getLogger(__name__)


def _illust_is_after(illust: dict, cutoff: datetime | None) -> bool:
    """True if the illust was created at/after the cutoff (or cannot be judged).

    Missing/unparseable create_date keeps the illust — import-side SHA dedup
    handles a redundant download, while dropping it could lose new work.
    """
    if cutoff is None:
        return True
    raw = illust.get("create_date")
    if not raw:
        return True
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created >= cutoff


async def download_pixiv_user_works(
    user_id: int,
    refresh_token: str,
    output_dir: Path,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    pause_check: Callable[[], Awaitable[bool]] | None = None,
    max_illusts: int = 0,
    on_file: Callable[[Path], Awaitable[None]] | None = None,
    date_after: datetime | None = None,
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
        date_after: Incremental cutoff (subscription re-checks). Illusts
            created before this are skipped and pagination stops at the first
            page that crosses the cutoff — the API returns newest-first, so a
            full-catalog walk on every re-check is wasted traffic.

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
                for attempt in range(_RATE_LIMIT_ATTEMPTS):
                    try:
                        data = await client.user_illusts(user_id, offset=offset)
                        break
                    except PixivRateLimitError as limited:
                        if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                            raise
                        if not await _wait_out_rate_limit(limited.retry_after, cancel_check):
                            return {"status": "cancelled", "downloaded": 0, "total": len(all_illusts), "failed": []}
            except PixivRateLimitError as exc:
                # A truncated catalogue must not finish as "done": the next
                # incremental check would believe the missing works were seen.
                logger.error("Pixiv rate limit while listing user %d at offset %d: %s", user_id, offset, exc)
                return {
                    "status": "failed",
                    "downloaded": 0,
                    "total": len(all_illusts),
                    "failed": [],
                    "error": str(exc),
                }
            except Exception as exc:
                logger.error("Failed to fetch user %d illusts at offset %d: %s", user_id, offset, exc)
                break

            illusts = data.get("illusts", [])
            if not illusts:
                break

            fresh = [i for i in illusts if _illust_is_after(i, date_after)]
            all_illusts.extend(fresh)

            # Crossed the incremental cutoff — pages are newest-first, so
            # everything further back is older. Stop paginating.
            if date_after is not None and len(fresh) < len(illusts):
                break

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
                    on_file=on_file,
                    filename_prefix=str(illust_id),
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
                elif result.get("rate_limited"):
                    # Every remaining artwork would wait out the same cooldown.
                    return {
                        "status": "failed",
                        "downloaded": downloaded,
                        "total": total,
                        "failed": [*failed, illust_id],
                        "error": result["error"],
                    }
                else:
                    failed.append(illust_id)

                if on_progress:
                    await on_progress(downloaded, total)

                await asyncio.sleep(
                    await get_typed_download_delay("pixiv", "illust", 2000)
                )  # Rate limit between illustrations

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
