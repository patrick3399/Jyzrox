"""Explorer query and selection endpoints."""

import json
import uuid
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.database import get_db
from core.gallery_helpers import (
    build_cover_map,
    get_favorite_set,
    get_rating_map,
    get_reading_list_set,
)
from core.redis_client import get_redis
from db.models import (
    Blob,
    Gallery,
    Image,
)
from services.explorer_query import (
    UNCATEGORIZED,
    ExplorerQuerySpec,
    build_explorer_gallery_query,
    normalize_explorer_query,
)
from services.explorer_requests import (
    CreateSelectionRequest,
    ExplorerQueryRequest,
)

router = APIRouter()
_member = require_role("member")


@router.post("/query")
async def query_explorer(
    request: ExplorerQueryRequest,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Query virtual Workbench nodes using predicate-style filters."""
    spec = await normalize_explorer_query(
        db,
        ExplorerQuerySpec(
            node_kind=request.node_kind,
            node_id=request.node_id,
            query=request.query,
            sort=request.sort,
            direction=request.direction,
            category=request.category,
        ),
        auth,
    )
    statement = build_explorer_gallery_query(spec, auth)
    total = (await db.execute(select(func.count()).select_from(statement.order_by(None).subquery()))).scalar_one()
    galleries = (await db.execute(statement.offset(request.offset).limit(request.limit))).scalars().all()
    gallery_ids = [gallery.id for gallery in galleries]
    cover_map = await build_cover_map(db, gallery_ids, {gallery.id: gallery.source for gallery in galleries})
    favorite_set = await get_favorite_set(db, auth["user_id"], gallery_ids)
    rating_map = await get_rating_map(db, auth["user_id"], gallery_ids)
    reading_set = await get_reading_list_set(db, auth["user_id"], gallery_ids)

    logical_sizes: dict[int, int] = {}
    unique_sizes: dict[int, int] = {}
    if gallery_ids:
        logical_sizes = {
            row.gallery_id: int(row.size)
            for row in (
                await db.execute(
                    select(Image.gallery_id, func.coalesce(func.sum(Blob.file_size), 0).label("size"))
                    .join(Blob, Blob.sha256 == Image.blob_sha256)
                    .where(Image.gallery_id.in_(gallery_ids))
                    .group_by(Image.gallery_id)
                )
            ).all()
        }
        unique_rows = (
            select(Image.gallery_id.label("gallery_id"), Image.blob_sha256, Blob.file_size.label("size"))
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.gallery_id.in_(gallery_ids))
            .distinct()
            .subquery()
        )
        unique_sizes = {
            row.gallery_id: int(row.size)
            for row in (
                await db.execute(
                    select(unique_rows.c.gallery_id, func.sum(unique_rows.c.size).label("size")).group_by(
                        unique_rows.c.gallery_id
                    )
                )
            ).all()
        }

    response: dict[str, Any] = {
        "total": total,
        "offset": request.offset,
        "limit": request.limit,
        "items": [
            {
                "id": gallery.id,
                "source": gallery.source,
                "source_id": gallery.source_id,
                "title": gallery.title,
                "title_jpn": gallery.title_jpn,
                "category": gallery.category,
                "language": gallery.language,
                "artist_id": gallery.artist_id,
                "uploader": gallery.uploader,
                "visibility": gallery.visibility,
                "pages": gallery.pages,
                "cover_thumb": cover_map.get(gallery.id),
                "logical_bytes": logical_sizes.get(gallery.id, 0),
                "unique_cas_bytes": unique_sizes.get(gallery.id, 0),
                "is_favorited": gallery.id in favorite_set,
                "my_rating": rating_map.get(gallery.id),
                "in_reading_list": gallery.id in reading_set,
                "deleted_at": gallery.deleted_at,
            }
            for gallery in galleries
        ],
    }
    if request.facets:
        # Same node + search filters, but ignoring the active category so every
        # dropdown option keeps its count while one is selected.
        facet_ids = build_explorer_gallery_query(replace(spec, category=None), auth).order_by(None).subquery()
        facet_key = case(
            (or_(facet_ids.c.category.is_(None), facet_ids.c.category == ""), UNCATEGORIZED),
            else_=facet_ids.c.category,
        ).label("facet_key")
        rows = (await db.execute(select(facet_key, func.count().label("count")).group_by(facet_key))).all()
        response["category_counts"] = {row.facet_key: int(row.count) for row in rows}
    return response


@router.post("/selections", status_code=201)
async def create_query_selection(
    request: CreateSelectionRequest,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Materialize all accessible Gallery ids for query-wide selection."""
    spec = await normalize_explorer_query(
        db,
        ExplorerQuerySpec(
            node_kind=request.query.node_kind,
            node_id=request.query.node_id,
            query=request.query.query,
            sort=request.query.sort,
            direction=request.query.direction,
            category=request.query.category,
        ),
        auth,
    )
    statement = build_explorer_gallery_query(spec, auth).with_only_columns(Gallery.id).order_by(None).limit(20_001)
    gallery_ids = list((await db.execute(statement)).scalars())
    if len(gallery_ids) > 20_000:
        raise HTTPException(status_code=413, detail="Query selection exceeds the 20,000 gallery limit")
    token = str(uuid.uuid4())
    payload = {
        "user_id": auth["user_id"],
        "gallery_ids": gallery_ids,
        "created_from": request.query.model_dump(exclude={"offset", "limit"}),
    }
    redis = get_redis()
    await redis.setex(f"explorer:selection:{token}", 1800, json.dumps(payload))
    return {"selection_token": token, "count": len(gallery_ids), "expires_in": 1800}
