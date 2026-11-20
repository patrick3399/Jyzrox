"""Explorer bulk gallery action endpoint."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    Collection,
    CollectionGallery,
    GalleryTag,
    Tag,
    UserFavorite,
    UserRating,
    UserReadingList,
    WorkbenchOperation,
)
from services.explorer_requests import (
    BulkActionRequest,
)
from services.explorer_requests import (
    resolve_bulk_selection as _resolve_bulk_selection,
)
from services.workbench_metadata import (
    load_accessible_galleries,
    load_writable_galleries,
)

router = APIRouter()
_member = require_role("member")


@router.post("/operations/action")
async def bulk_gallery_action(
    request: BulkActionRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Apply tag, collection, rating, favorite, or read-later changes."""
    from datetime import UTC, datetime

    from services.tag_helpers import parse_tag_strings

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    if request.action in {
        "favorite",
        "unfavorite",
        "rate",
        "add_read_later",
        "remove_read_later",
        "add_collection",
        "remove_collection",
    }:
        galleries = await load_accessible_galleries(db, gallery_ids, auth)
    else:
        galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    affected = 0

    if request.action in {"favorite", "unfavorite"}:
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserFavorite).where(
                        UserFavorite.user_id == auth["user_id"], UserFavorite.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        if request.action == "favorite":
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    db.add(UserFavorite(user_id=auth["user_id"], gallery_id=gallery_id))
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
    elif request.action in {"add_read_later", "remove_read_later"}:
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserReadingList).where(
                        UserReadingList.user_id == auth["user_id"], UserReadingList.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        if request.action == "add_read_later":
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    db.add(UserReadingList(user_id=auth["user_id"], gallery_id=gallery_id))
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
    elif request.action == "rate":
        if request.rating is None:
            raise HTTPException(status_code=400, detail="rating is required")
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserRating).where(
                        UserRating.user_id == auth["user_id"], UserRating.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        for gallery_id in gallery_ids:
            row = existing.get(gallery_id)
            if request.rating == 0:
                if row is not None:
                    await db.delete(row)
                    affected += 1
            elif row is None:
                db.add(UserRating(user_id=auth["user_id"], gallery_id=gallery_id, rating=request.rating))
                affected += 1
            elif row.rating != request.rating:
                row.rating = request.rating
                row.rated_at = datetime.now(UTC)
                affected += 1
    elif request.action in {"add_collection", "remove_collection"}:
        if request.collection_id is None:
            raise HTTPException(status_code=400, detail="collection_id is required")
        collection = await db.get(Collection, request.collection_id)
        if collection is None or (auth["role"] != "admin" and collection.user_id != auth["user_id"]):
            raise HTTPException(status_code=404, detail="Collection not found")
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(CollectionGallery).where(
                        CollectionGallery.collection_id == request.collection_id,
                        CollectionGallery.gallery_id.in_(gallery_ids),
                    )
                )
            ).scalars()
        }
        if request.action == "add_collection":
            position = (
                await db.execute(
                    select(func.coalesce(func.max(CollectionGallery.position), -1)).where(
                        CollectionGallery.collection_id == request.collection_id
                    )
                )
            ).scalar_one()
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    position += 1
                    db.add(
                        CollectionGallery(collection_id=request.collection_id, gallery_id=gallery_id, position=position)
                    )
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
        collection.updated_at = datetime.now(UTC)
    else:
        parsed = parse_tag_strings(request.tags)
        if not parsed:
            raise HTTPException(status_code=400, detail="At least one valid tag is required")
        tags = (
            (
                await db.execute(
                    select(Tag).where(
                        or_(*[(Tag.namespace == namespace) & (Tag.name == name) for namespace, name in parsed])
                    )
                )
            )
            .scalars()
            .all()
        )
        by_value = {(tag.namespace, tag.name): tag for tag in tags}
        if request.action == "add_tags":
            for namespace, name in parsed:
                if (namespace, name) not in by_value:
                    tag = Tag(namespace=namespace, name=name, count=0)
                    db.add(tag)
                    await db.flush()
                    by_value[(namespace, name)] = tag
        tag_ids = [tag.id for tag in by_value.values()]
        existing_rows = (
            (
                await db.execute(
                    select(GalleryTag).where(GalleryTag.gallery_id.in_(gallery_ids), GalleryTag.tag_id.in_(tag_ids))
                )
            )
            .scalars()
            .all()
        )
        existing = {(row.gallery_id, row.tag_id): row for row in existing_rows}
        if request.action == "add_tags":
            for gallery_id in gallery_ids:
                for tag_id in tag_ids:
                    if (gallery_id, tag_id) not in existing:
                        db.add(GalleryTag(gallery_id=gallery_id, tag_id=tag_id, confidence=1.0, source="manual"))
                        affected += 1
        else:
            for row in existing_rows:
                if row.source == "manual":
                    await db.delete(row)
                    affected += 1
        await db.flush()
        tag_rows = (
            await db.execute(
                select(GalleryTag.gallery_id, Tag.namespace, Tag.name)
                .join(Tag, Tag.id == GalleryTag.tag_id)
                .where(GalleryTag.gallery_id.in_(gallery_ids))
                .order_by(Tag.namespace, Tag.name)
            )
        ).all()
        tags_by_gallery: dict[int, list[str]] = {gallery_id: [] for gallery_id in gallery_ids}
        for row in tag_rows:
            tags_by_gallery[row.gallery_id].append(f"{row.namespace}:{row.name}")
        for gallery in galleries:
            gallery.tags_array = tags_by_gallery[gallery.id]
        for tag_id in tag_ids:
            count = (
                await db.execute(select(func.count()).select_from(GalleryTag).where(GalleryTag.tag_id == tag_id))
            ).scalar_one()
            tag = next(tag for tag in by_value.values() if tag.id == tag_id)
            tag.count = count

    now = datetime.now(UTC)
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind=request.action,
        status="completed",
        selection_count=len(galleries),
        params=request.model_dump(exclude={"selection_token"}),
        progress={"affected": affected},
        started_at=now,
        finished_at=now,
    )
    db.add(operation)
    await db.commit()
    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action=request.action,
        gallery_ids=gallery_ids,
    )
    return {"operation_id": str(operation.id), "status": "completed", "affected": affected}
