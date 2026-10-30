"""Gallery lifecycle operations: hard delete with blob ref-counting and filesystem cleanup.

Extracted from routers/library._hard_delete_galleries so that worker/trash.py
can call it without importing a router module (STAB-004).

Known edge case #55: DB commit happens before filesystem cleanup. If the process
dies between commit and file removal, orphan directories may remain.
Accepted risk — reconciliation can clean these up.
"""

import asyncio
import logging
import shutil

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.redis_client import get_redis
from db.models import DownloadJob, Gallery, Image
from services.cas import decrement_ref_count, library_dir
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails

logger = logging.getLogger(__name__)

_SOURCES_CACHE_KEY = "library:sources"
_ACTIVE_JOB_STATUSES = ("queued", "running", "paused")


async def invalidate_sources_cache() -> None:
    """Delete the cached sources list so the next request re-queries."""
    try:
        await get_redis().delete(_SOURCES_CACHE_KEY)
    except Exception:
        pass


def _delete_library_dirs_sync(galleries: list) -> int:
    deleted = 0
    for g in galleries:
        lib_dir = library_dir(g.source, g.source_id)
        if lib_dir.exists():
            try:
                shutil.rmtree(str(lib_dir), ignore_errors=True)
                deleted += 1
            except OSError as exc:
                logger.warning("[hard_delete] failed to remove library dir %s: %s", lib_dir, exc)
    return deleted


async def hard_delete_galleries(db: AsyncSession, galleries: list[Gallery]) -> dict:
    """Permanently delete galleries: decrement blob refs, remove DB records, cleanup filesystem."""
    if not galleries:
        return {"affected": 0, "deleted_dirs": 0}

    img_stmt = select(Image).where(Image.gallery_id.in_([g.id for g in galleries])).options(selectinload(Image.blob))
    images = (await db.execute(img_stmt)).scalars().all()
    # A pending link page has no blob (and so no reference to give back).
    blob_sha256s = [img.blob_sha256 for img in images if img.blob_sha256 is not None]

    for sha256 in blob_sha256s:
        await decrement_ref_count(sha256, db)

    for g in galleries:
        await db.delete(g)
    await db.commit()

    await invalidate_sources_cache()

    try:
        deleted_count = await asyncio.to_thread(_delete_library_dirs_sync, galleries)
        zero_ref_sha256s = await cleanup_unreferenced_thumbnails(db, blob_sha256s)
        deleted_count += len(zero_ref_sha256s)
    except Exception as exc:
        logger.warning("[hard_delete] cleanup failed: %s", exc)
        deleted_count = 0

    return {"affected": len(galleries), "deleted_dirs": deleted_count}


async def settle_stale_downloading_galleries(db: AsyncSession, gallery_ids: list[int]) -> int:
    """Move galleries stuck on ``downloading`` that no active job owns to ``partial`` (or ``proxy_only`` if empty).

    A job that ended without finalizing its gallery (worker killed, keep path
    failed after the stop claim) leaves it on ``downloading`` for good.
    Trashed galleries are never touched (BE-T17). Returns how many galleries
    changed; the caller commits.
    """
    if not gallery_ids:
        return 0

    unique_gallery_ids = list(set(gallery_ids))
    active_ids = set(
        (
            await db.execute(
                select(DownloadJob.gallery_id).where(
                    DownloadJob.gallery_id.in_(unique_gallery_ids),
                    DownloadJob.status.in_(_ACTIVE_JOB_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    stale_ids = [gid for gid in unique_gallery_ids if gid not in active_ids]
    if not stale_ids:
        return 0

    image_counts = {
        gid: count
        for gid, count in (
            await db.execute(
                select(Image.gallery_id, func.count()).where(Image.gallery_id.in_(stale_ids)).group_by(Image.gallery_id)
            )
        ).all()
    }

    partial_ids = [gid for gid in stale_ids if image_counts.get(gid, 0) > 0]
    empty_ids = [gid for gid in stale_ids if image_counts.get(gid, 0) == 0]
    stuck = (Gallery.download_status == "downloading", Gallery.deleted_at.is_(None))

    settled = 0
    if partial_ids:
        result = await db.execute(
            update(Gallery).where(Gallery.id.in_(partial_ids), *stuck).values(download_status="partial")
        )
        settled += result.rowcount or 0
    if empty_ids:
        result = await db.execute(
            update(Gallery).where(Gallery.id.in_(empty_ids), *stuck).values(download_status="proxy_only", pages=0)
        )
        settled += result.rowcount or 0
    return settled
