"""Shared collection-membership write logic.

Both ``POST /api/collections/{id}/galleries`` and the library batch
``add_to_collection`` action add galleries to a collection. They share this
service so the visibility rules cannot drift apart.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import Collection, CollectionGallery, Gallery


async def add_galleries_to_collection(
    db: AsyncSession,
    collection: Collection,
    gallery_ids: list[int],
    auth: dict,
) -> tuple[int, list[int]]:
    """Add visible galleries to ``collection``.

    Returns ``(added_count, denied_ids)``. ``denied_ids`` holds ids that do not
    exist or that the caller cannot read (``gallery_access_filter`` also excludes
    trashed galleries). Ids already in the collection are skipped silently.

    The caller owns the transaction: it must commit and emit
    ``EventType.COLLECTION_UPDATED`` afterwards. Ownership of ``collection`` must
    already have been verified by the caller.
    """
    ids = list(dict.fromkeys(gallery_ids))
    if not ids:
        return 0, []

    visible = set(
        (await db.execute(select(Gallery.id).where(Gallery.id.in_(ids), gallery_access_filter(auth)))).scalars().all()
    )
    denied = [gid for gid in ids if gid not in visible]

    existing = (
        set(
            (
                await db.execute(
                    select(CollectionGallery.gallery_id).where(
                        CollectionGallery.collection_id == collection.id,
                        CollectionGallery.gallery_id.in_(list(visible)),
                    )
                )
            )
            .scalars()
            .all()
        )
        if visible
        else set()
    )

    to_add = [gid for gid in ids if gid in visible and gid not in existing]
    if to_add:
        max_pos = (
            await db.execute(
                select(func.coalesce(func.max(CollectionGallery.position), -1)).where(
                    CollectionGallery.collection_id == collection.id
                )
            )
        ).scalar_one()
        for offset, gid in enumerate(to_add, start=1):
            db.add(CollectionGallery(collection_id=collection.id, gallery_id=gid, position=max_pos + offset))

    collection.updated_at = datetime.now(UTC)
    return len(to_add), denied
