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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.redis_client import get_redis
from db.models import Blob, Gallery, Image
from services.cas import decrement_ref_count, library_dir, thumb_dir

logger = logging.getLogger(__name__)

_SOURCES_CACHE_KEY = "library:sources"


async def invalidate_sources_cache() -> None:
    """Delete the cached sources list so the next request re-queries."""
    try:
        await get_redis().delete(_SOURCES_CACHE_KEY)
    except Exception:
        pass


def _delete_filesystem_sync(galleries: list, zero_ref_sha256s: set[str]) -> int:
    deleted = 0
    for g in galleries:
        lib_dir = library_dir(g.source, g.source_id)
        if lib_dir.exists():
            try:
                shutil.rmtree(str(lib_dir), ignore_errors=True)
                deleted += 1
            except OSError as exc:
                logger.warning("[hard_delete] failed to remove library dir %s: %s", lib_dir, exc)
    for sha256 in zero_ref_sha256s:
        td = thumb_dir(sha256)
        if td.exists():
            try:
                shutil.rmtree(str(td), ignore_errors=True)
                deleted += 1
            except OSError as exc:
                logger.warning("[hard_delete] failed to remove thumb dir %s: %s", td, exc)
    return deleted


async def hard_delete_galleries(db: AsyncSession, galleries: list[Gallery]) -> dict:
    """Permanently delete galleries: decrement blob refs, remove DB records, cleanup filesystem."""
    if not galleries:
        return {"affected": 0, "deleted_dirs": 0}

    img_stmt = select(Image).where(Image.gallery_id.in_([g.id for g in galleries])).options(selectinload(Image.blob))
    images = (await db.execute(img_stmt)).scalars().all()
    blob_sha256s = [img.blob_sha256 for img in images]

    for sha256 in blob_sha256s:
        await decrement_ref_count(sha256, db)

    for g in galleries:
        await db.delete(g)
    await db.commit()

    await invalidate_sources_cache()

    zero_ref_sha256s: set[str] = set()
    if blob_sha256s:
        zero_ref_result = await db.execute(
            select(Blob.sha256).where(Blob.sha256.in_(blob_sha256s), Blob.ref_count <= 0)
        )
        zero_ref_sha256s = set(zero_ref_result.scalars().all())

    try:
        deleted_count = await asyncio.to_thread(_delete_filesystem_sync, galleries, zero_ref_sha256s)
    except Exception as exc:
        logger.warning("[hard_delete] cleanup failed: %s", exc)
        deleted_count = 0

    return {"affected": len(galleries), "deleted_dirs": deleted_count}
