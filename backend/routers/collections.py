"""Collection management — group galleries into named collections."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from core.gallery_helpers import build_cover_sha_map
from db.models import Collection, CollectionGallery, Gallery
from services.cas import thumb_url as cas_thumb_url
from services.collection_membership import add_galleries_to_collection as add_galleries_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["collections"])


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None


class CollectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    cover_gallery_id: int | None = None


class AddGalleries(BaseModel):
    gallery_ids: list[int]


@router.get("/")
async def list_collections(
    gallery_id: int | None = Query(default=None),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all collections with gallery count and cover thumbnail.

    Counts and covers only consider galleries visible to the caller. When
    ``gallery_id`` is given, each entry gets ``contains_gallery`` (membership flag).
    """
    collections = (
        (
            await db.execute(
                select(Collection).where(Collection.user_id == auth["user_id"]).order_by(Collection.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    collection_ids = [c.id for c in collections]

    # Visible gallery count per collection (same access filter as get_collection)
    counts: dict[int, int] = {}
    # First visible gallery per collection (fallback cover), by position then added_at
    first_visible: dict[int, int] = {}
    if collection_ids:
        counts = {
            cid: n
            for cid, n in (
                await db.execute(
                    select(CollectionGallery.collection_id, func.count())
                    .join(Gallery, CollectionGallery.gallery_id == Gallery.id)
                    .where(CollectionGallery.collection_id.in_(collection_ids), gallery_access_filter(auth))
                    .group_by(CollectionGallery.collection_id)
                )
            ).all()
        }
        ranked = (
            select(
                CollectionGallery.collection_id.label("collection_id"),
                CollectionGallery.gallery_id.label("gallery_id"),
                func.row_number()
                .over(
                    partition_by=CollectionGallery.collection_id,
                    order_by=(CollectionGallery.position, CollectionGallery.added_at),
                )
                .label("rn"),
            )
            .join(Gallery, CollectionGallery.gallery_id == Gallery.id)
            .where(CollectionGallery.collection_id.in_(collection_ids), gallery_access_filter(auth))
            .subquery()
        )
        first_visible = {
            cid: gid
            for cid, gid in (
                await db.execute(select(ranked.c.collection_id, ranked.c.gallery_id).where(ranked.c.rn == 1))
            )
            .tuples()
            .all()
        }

    # Explicit covers only count if the gallery is still visible to the caller
    explicit_ids = {c.cover_gallery_id for c in collections if c.cover_gallery_id}
    visible_explicit: set[int] = set()
    if explicit_ids:
        visible_explicit = set(
            (await db.execute(select(Gallery.id).where(Gallery.id.in_(explicit_ids), gallery_access_filter(auth))))
            .scalars()
            .all()
        )

    cover_gid_by_collection: dict[int, int] = {}
    for collection in collections:
        if collection.cover_gallery_id and collection.cover_gallery_id in visible_explicit:
            cover_gid_by_collection[collection.id] = collection.cover_gallery_id
        elif collection.id in first_visible:
            cover_gid_by_collection[collection.id] = first_visible[collection.id]

    cover_gids = list(set(cover_gid_by_collection.values()))
    cover_sha: dict[int, str] = {}
    if cover_gids:
        source_rows = (await db.execute(select(Gallery.id, Gallery.source).where(Gallery.id.in_(cover_gids)))).all()
        cover_sha = await build_cover_sha_map(db, cover_gids, {gid: src or "" for gid, src in source_rows})

    member_of: set[int] = set()
    if gallery_id is not None and collection_ids:
        member_of = set(
            (
                await db.execute(
                    select(CollectionGallery.collection_id).where(
                        CollectionGallery.collection_id.in_(collection_ids),
                        CollectionGallery.gallery_id == gallery_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    result = []
    for collection in collections:
        sha = cover_sha.get(cover_gid_by_collection.get(collection.id, -1))
        entry = {
            "id": collection.id,
            "name": collection.name,
            "description": collection.description,
            "cover_gallery_id": collection.cover_gallery_id,
            "gallery_count": counts.get(collection.id, 0),
            "cover_thumb": cas_thumb_url(sha) if sha else None,
            "created_at": collection.created_at.isoformat() if collection.created_at else None,
            "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
        }
        if gallery_id is not None:
            entry["contains_gallery"] = collection.id in member_of
        result.append(entry)

    return {"collections": result}


@router.post("/")
async def create_collection(
    body: CollectionCreate,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a new collection."""
    collection = Collection(name=body.name, description=body.description, user_id=auth["user_id"])
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.COLLECTION_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="collection",
        resource_id=collection.id,
    )
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "created_at": collection.created_at.isoformat() if collection.created_at else None,
    }


@router.get("/{collection_id}")
async def get_collection(
    collection_id: int,
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get collection details with paginated gallery list."""
    collection = await db.get(Collection, collection_id)
    if not collection or collection.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Count galleries — apply access filter so trashed/inaccessible galleries
    # are excluded from pagination totals (edge case #100)
    count_stmt = (
        select(func.count())
        .select_from(CollectionGallery)
        .join(Gallery, CollectionGallery.gallery_id == Gallery.id)
        .where(CollectionGallery.collection_id == collection_id, gallery_access_filter(auth))
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # Get galleries with covers — same access filter applied
    cg_stmt = (
        select(CollectionGallery)
        .join(Gallery, CollectionGallery.gallery_id == Gallery.id)
        .where(CollectionGallery.collection_id == collection_id, gallery_access_filter(auth))
        .order_by(CollectionGallery.position, CollectionGallery.added_at)
        .offset(page * limit)
        .limit(limit)
        .options(selectinload(CollectionGallery.gallery))
    )
    cg_rows = (await db.execute(cg_stmt)).scalars().all()

    gallery_ids = [cg.gallery_id for cg in cg_rows]
    source_map_col = {cg.gallery_id: (cg.gallery.source or "") for cg in cg_rows if cg.gallery}
    cover_map = {
        gallery_id: cas_thumb_url(sha256)
        for gallery_id, sha256 in (await build_cover_sha_map(db, gallery_ids, source_map_col)).items()
    }

    galleries = []
    for cg in cg_rows:
        g = cg.gallery
        if not g:
            continue
        galleries.append(
            {
                "id": g.id,
                "source": g.source,
                "source_id": g.source_id,
                "title": g.title,
                "title_jpn": g.title_jpn,
                "category": g.category,
                "pages": g.pages,
                "rating": g.rating,
                "favorited": g.favorited,
                "added_at": g.added_at.isoformat() if g.added_at else None,
                "cover_thumb": cover_map.get(g.id),
                "position": cg.position,
                "added_to_collection_at": cg.added_at.isoformat() if cg.added_at else None,
            }
        )

    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "cover_gallery_id": collection.cover_gallery_id,
        "gallery_count": total,
        "galleries": galleries,
        "page": page,
        "has_next": (page + 1) * limit < total,
        "created_at": collection.created_at.isoformat() if collection.created_at else None,
        "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
    }


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
