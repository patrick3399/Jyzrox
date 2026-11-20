"""Library split from routers/library.py (library_batch_ops)."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Gallery,
)
from services.gallery_lifecycle import (
    invalidate_sources_cache as _invalidate_sources_cache,
)
from services.gallery_lifecycle import (
    mark_trashed,
)
from services.library_helpers import check_write_access as _check_write_access


class BatchAction(BaseModel):
    action: Literal[
        "delete",
        "favorite",
        "unfavorite",
        "rate",
        "add_to_collection",
        "add_tags",
        "remove_tags",
        "add_to_reading_list",
        "remove_from_reading_list",
    ]
    gallery_ids: list[int]  # max 100
    rating: int | None = None  # required when action=rate
    collection_id: int | None = None  # required when action=add_to_collection
    tags: list[str] | None = None  # required when action=add_tags or remove_tags


async def batch_delete_galleries(db: AsyncSession, gallery_ids: list[int], auth: dict) -> dict:
    """Soft-delete multiple galleries by setting deleted_at timestamp."""
    # Load all galleries
    stmt = select(Gallery).where(Gallery.id.in_(gallery_ids))
    galleries = (await db.execute(stmt)).scalars().all()
    if not galleries:
        return {"status": "ok", "affected": 0, "deleted_dirs": 0}

    for g in galleries:
        _check_write_access(auth, g)

    # Filter out galleries with active downloads (skip rather than reject for batch)
    from db.models import DownloadJob

    active_gallery_ids_result = await db.execute(
        select(DownloadJob.gallery_id).where(
            DownloadJob.gallery_id.in_([g.id for g in galleries]),
            DownloadJob.status.in_(["queued", "running", "paused"]),
        )
    )
    active_gallery_ids = set(active_gallery_ids_result.scalars().all())
    skip_ids = active_gallery_ids
    if skip_ids:
        galleries = [g for g in galleries if g.id not in skip_ids]
        if not galleries:
            return {"status": "ok", "affected": 0, "deleted_dirs": 0, "skipped": len(skip_ids)}

    mark_trashed(galleries, reason="user", actor_user_id=auth["user_id"])
    await db.commit()
    await _invalidate_sources_cache()
    return {"status": "ok", "affected": len(galleries), "deleted_dirs": 0}
