"""Collection update, delete, and membership endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from db.models import Collection, CollectionGallery, Gallery
from services.collection_membership import add_galleries_to_collection as add_galleries_service

router = APIRouter()


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    cover_gallery_id: int | None = None


class AddGalleries(BaseModel):
    gallery_ids: list[int]


@router.patch("/{collection_id}")
async def update_collection(
    collection_id: int,
    patch: CollectionPatch,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update collection name/description/cover."""
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Collection not found")

    if patch.name is not None:
        collection.name = patch.name
    if patch.description is not None:
        collection.description = patch.description
    if patch.cover_gallery_id is not None:
        # Edge case #125: the cover gallery must be visible to the caller. Without
        # this check a user could point their collection cover at another user's
        # private gallery and read its CAS thumbnail via list_collections.
        cover_visible = (
            await db.execute(
                select(Gallery.id).where(
                    Gallery.id == patch.cover_gallery_id,
                    gallery_access_filter(auth),
                )
            )
        ).scalar_one_or_none()
        if cover_visible is None:
            raise HTTPException(status_code=404, detail="Cover gallery not found")
        collection.cover_gallery_id = patch.cover_gallery_id

    collection.updated_at = datetime.now(UTC)
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.COLLECTION_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="collection",
        resource_id=collection_id,
    )
    return {"status": "ok"}


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: int,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a collection (does not delete galleries)."""
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.delete(collection)
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.COLLECTION_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="collection",
        resource_id=collection_id,
    )
    return {"status": "ok"}


@router.post("/{collection_id}/galleries")
async def add_galleries_to_collection(
    collection_id: int,
    body: AddGalleries,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Add galleries to a collection."""
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Collection not found")

    added, denied = await add_galleries_service(db, collection, body.gallery_ids, auth)
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.COLLECTION_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="collection",
        resource_id=collection_id,
    )
    return {"status": "ok", "added": added, "denied": denied}


@router.delete("/{collection_id}/galleries/{gallery_id}")
async def remove_gallery_from_collection(
    collection_id: int,
    gallery_id: int,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Remove a gallery from a collection."""
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Collection not found")

    result = await db.execute(
        delete(CollectionGallery).where(
            CollectionGallery.collection_id == collection_id,
            CollectionGallery.gallery_id == gallery_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Gallery not in collection")

    collection.updated_at = datetime.now(UTC)
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.COLLECTION_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="collection",
        resource_id=collection_id,
    )
    return {"status": "ok"}
