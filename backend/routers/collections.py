"""Collection management — group galleries into named collections."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import require_auth
from core.database import get_db
from db.models import Collection, CollectionGallery, Gallery, Image, Blob
from services.cas import thumb_url as cas_thumb_url
from core.source_display import get_display_config

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
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all collections with gallery count and cover thumbnail."""
    stmt = (
        select(
            Collection,
            func.count(CollectionGallery.gallery_id).label("gallery_count"),
        )
        .where(Collection.user_id == auth["user_id"])
        .outerjoin(CollectionGallery, Collection.id == CollectionGallery.collection_id)
        .group_by(Collection.id)
        .order_by(Collection.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    result = []
    for collection, gallery_count in rows:
        # Get cover thumbnail
        cover_thumb = None
        cover_gid = collection.cover_gallery_id
        if not cover_gid:
            # Use the first gallery's cover if no explicit cover set
            first_cg = (
                await db.execute(
                    select(CollectionGallery.gallery_id)
                    .where(CollectionGallery.collection_id == collection.id)
                    .order_by(CollectionGallery.position, CollectionGallery.added_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if first_cg:
                cover_gid = first_cg

        if cover_gid:
            # Per-source cover page selection
            cover_gallery = await db.get(Gallery, cover_gid)
            cfg = get_display_config((cover_gallery.source if cover_gallery else "") or "")
            if cfg.cover_page == "last":
                page_sub = (
                    select(func.max(Image.page_num))
                    .where(Image.gallery_id == cover_gid)
                    .scalar_subquery()
                )
            else:
                page_sub = 1
            cover_row = (
                await db.execute(
                    select(Blob.sha256)
                    .join(Image, Image.blob_sha256 == Blob.sha256)
                    .where(Image.gallery_id == cover_gid, Image.page_num == page_sub)
                )
            ).scalar_one_or_none()
            if cover_row:
                cover_thumb = cas_thumb_url(cover_row)

        result.append({
            "id": collection.id,
            "name": collection.name,
            "description": collection.description,
            "cover_gallery_id": collection.cover_gallery_id,
            "gallery_count": gallery_count,
            "cover_thumb": cover_thumb,
            "created_at": collection.created_at.isoformat() if collection.created_at else None,
            "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
        })

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

    # Count galleries
    count_stmt = select(func.count()).where(CollectionGallery.collection_id == collection_id)
    total = (await db.execute(count_stmt)).scalar_one()

    # Get galleries with covers
    cg_stmt = (
        select(CollectionGallery)
        .where(CollectionGallery.collection_id == collection_id)
        .order_by(CollectionGallery.position, CollectionGallery.added_at)
        .offset(page * limit)
        .limit(limit)
        .options(selectinload(CollectionGallery.gallery))
    )
    cg_rows = (await db.execute(cg_stmt)).scalars().all()

    gallery_ids = [cg.gallery_id for cg in cg_rows]
    # Per-source cover map
    source_map_col = {cg.gallery_id: (cg.gallery.source or "") for cg in cg_rows if cg.gallery}
    first_ids = [gid for gid in gallery_ids if get_display_config(source_map_col.get(gid, "")).cover_page == "first"]
    last_ids = [gid for gid in gallery_ids if get_display_config(source_map_col.get(gid, "")).cover_page == "last"]

    cover_map: dict[int, str] = {}
    if first_ids:
        first_stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .where(Image.gallery_id.in_(first_ids), Image.page_num == 1)
        )
        for r in (await db.execute(first_stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)
    if last_ids:
        max_page_sub = (
            select(Image.gallery_id, func.max(Image.page_num).label("max_page"))
            .where(Image.gallery_id.in_(last_ids))
            .group_by(Image.gallery_id)
        ).subquery()
        last_stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .join(max_page_sub, and_(Image.gallery_id == max_page_sub.c.gallery_id, Image.page_num == max_page_sub.c.max_page))
        )
        for r in (await db.execute(last_stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)

    galleries = []
    for cg in cg_rows:
        g = cg.gallery
        if not g:
            continue
        galleries.append({
            "id": g.id,
            "source": g.source,
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
        })

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
        collection.cover_gallery_id = patch.cover_gallery_id

    collection.updated_at = datetime.now(UTC)
    await db.commit()
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

    # Get current max position
    max_pos_result = (
        await db.execute(
            select(func.coalesce(func.max(CollectionGallery.position), -1))
            .where(CollectionGallery.collection_id == collection_id)
        )
    ).scalar_one()

    added = 0
    denied: list[int] = []
    position_offset = 0
    for gid in body.gallery_ids:
        # Check if already in collection
        existing = (
            await db.execute(
                select(CollectionGallery)
                .where(
                    CollectionGallery.collection_id == collection_id,
                    CollectionGallery.gallery_id == gid,
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        # Verify the gallery is visible to this user
        gallery = await db.get(Gallery, gid)
        if not gallery:
            denied.append(gid)
            continue
        if auth.get("role") != "admin":
            if (gallery.created_by_user_id is not None
                    and gallery.created_by_user_id != auth["user_id"]
                    and gallery.visibility != "public"):
                denied.append(gid)
                continue
        cg = CollectionGallery(
            collection_id=collection_id,
            gallery_id=gid,
            position=max_pos_result + 1 + position_offset,
        )
        db.add(cg)
        added += 1
        position_offset += 1

    collection.updated_at = datetime.now(UTC)
    await db.commit()
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
    return {"status": "ok"}
