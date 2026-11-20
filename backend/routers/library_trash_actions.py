"""Library split from routers/library.py (library_trash_actions)."""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import asc, desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.gallery_helpers import (
    build_cover_map,
)
from core.redis_client import get_redis
from core.source_display import get_display_config
from db.models import (
    Blob,
    ExcludedBlob,
    Gallery,
    Image,
    User,
)
from services.cas import (
    existing_base_thumbs,
)
from services.gallery_lifecycle import (
    restore_galleries,
)
from services.library_helpers import trash_filter as _trash_filter
from services.library_serializers import gallery_media_stats as _gallery_media_stats
from services.library_serializers import is_pending as _is_pending
from services.library_serializers import media_type as _media_type
from services.library_serializers import thumb_fields as _thumb_fields
from services.library_trash import TrashReasonFilter
from services.library_trash import purge_guard_key as _purge_guard_key
from services.library_trash import queue_purge as _queue_purge
from services.library_trash import trash_item as _trash_item
from services.library_trash import trash_query as _trash_query
from services.settings_store import get_int_setting as _get_int_setting

_build_cover_map = build_cover_map
_member = require_role("member")
router = APIRouter()


@router.get("/trash/summary")
async def trash_summary(
    q: str | None = Query(default=None, max_length=500),
    source: str | None = Query(default=None, max_length=100),
    reason: TrashReasonFilter | None = None,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Count, sizes, next expiry, sources and running-purge progress for the filtered trash."""
    id_stmt = _trash_query(auth, q, source, reason).with_only_columns(Gallery.id).order_by(None)
    filtered_ids = id_stmt.scalar_subquery()

    count, oldest = (
        await db.execute(
            select(func.count(), func.min(Gallery.deleted_at)).where(Gallery.id.in_(id_stmt.scalar_subquery()))
        )
    ).one()

    logical_bytes = (
        await db.execute(
            select(func.coalesce(func.sum(Blob.file_size), 0))
            .select_from(Image)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.gallery_id.in_(filtered_ids), Image.visibility == "active")
        )
    ).scalar_one()

    # Reclaimable: CAS blobs referenced by the filtered set and by no image outside it.
    inside = aliased(Image)
    outside = aliased(Image)
    reclaimable_bytes = (
        await db.execute(
            select(func.coalesce(func.sum(Blob.file_size), 0)).where(
                Blob.storage == "cas",
                exists().where(inside.blob_sha256 == Blob.sha256, inside.gallery_id.in_(id_stmt.scalar_subquery())),
                ~exists().where(
                    outside.blob_sha256 == Blob.sha256,
                    outside.gallery_id.not_in(id_stmt.scalar_subquery()),
                ),
            )
        )
    ).scalar_one()

    next_expiry_at = None
    if count and oldest is not None:
        retention_days = await _get_int_setting("setting:trash_retention_days", 30)
        if retention_days < 1:
            retention_days = 30
        next_expiry_at = (oldest + timedelta(days=retention_days)).isoformat()

    sources = sorted(
        s for s in (await db.execute(select(Gallery.source).where(_trash_filter(auth)).distinct())).scalars() if s
    )

    purge = None
    try:
        raw = await get_redis().get(_purge_guard_key(auth["user_id"]))
        if raw is not None:
            data = json.loads(raw)
            purge = {"done": int(data["done"]), "total": int(data["total"])}
    except Exception:
        purge = None

    return {
        "count": count,
        "logical_bytes": int(logical_bytes),
        "reclaimable_bytes": int(reclaimable_bytes),
        "next_expiry_at": next_expiry_at,
        "sources": sources,
        "purge": purge,
    }


class TrashRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gallery_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)
    all: bool = False
    q: str | None = None
    source: str | None = None
    reason: TrashReasonFilter | None = None

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> TrashRestoreBody:
        if (self.gallery_ids is not None) == bool(self.all):
            raise ValueError("Provide exactly one of gallery_ids or all=true")
        if not self.all and (self.q or self.source or self.reason):
            raise ValueError("q, source and reason require all=true")
        return self


class TrashPurgeBody(BaseModel):
    gallery_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/trash/restore")
async def restore_trash(
    body: TrashRestoreBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore many trashed galleries (or all in scope). Out-of-scope ids are ignored."""
    if body.gallery_ids is not None:
        stmt = select(Gallery).where(_trash_filter(auth), Gallery.id.in_(body.gallery_ids))
    else:
        stmt = _trash_query(auth, body.q, body.source, body.reason, "deleted_at", "desc")
    galleries = list((await db.execute(stmt)).scalars().all())
    ids = sorted(g.id for g in galleries)
    affected = await restore_galleries(db, galleries)
    if affected:
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.GALLERY_BATCH_UPDATED,
            actor_user_id=auth["user_id"],
            resource_type="gallery",
            action="restore",
            gallery_ids=ids,
        )
    return {"status": "ok", "affected": affected}


@router.post("/trash/purge", status_code=202)
async def purge_trash(
    body: TrashPurgeBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Queue permanent deletion of the selected trashed galleries. Out-of-scope ids are ignored."""
    ids = sorted(
        (await db.execute(select(Gallery.id).where(_trash_filter(auth), Gallery.id.in_(body.gallery_ids)))).scalars()
    )
    return await _queue_purge(auth, ids)


@router.get("/trash/{gallery_id}/preview")
async def preview_trash(
    gallery_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=60, ge=1, le=120),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Read-only preview of a trashed gallery: metadata, media stats, paged thumbnails (no file URLs)."""
    g = (await db.execute(select(Gallery).where(Gallery.id == gallery_id, _trash_filter(auth)))).scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")

    cover_map = await _build_cover_map(db, [g.id], {g.id: g.source})
    users: dict[int, str] = {}
    if g.deleted_by_user_id is not None:
        name = (await db.execute(select(User.username).where(User.id == g.deleted_by_user_id))).scalar_one_or_none()
        if name is not None:
            users[g.deleted_by_user_id] = name
    merged: dict[int, Gallery] = {}
    if g.merged_into_gallery_id is not None:
        target = (
            await db.execute(
                select(Gallery).where(
                    Gallery.id == g.merged_into_gallery_id,
                    Gallery.deleted_at.is_(None),
                    gallery_access_filter(auth),
                )
            )
        ).scalar_one_or_none()
        if target is not None:
            merged[target.id] = target

    stats = await _gallery_media_stats(db, g.id)

    page_order = (
        desc(Image.page_num) if get_display_config(g.source or "").image_order == "desc" else asc(Image.page_num)
    )
    excluded_sq = (
        select(ExcludedBlob.blob_sha256)
        .where(ExcludedBlob.gallery_id == g.id)
        .correlate(Image)
        .where(ExcludedBlob.blob_sha256 == Image.blob_sha256)
    )
    visible = (Image.gallery_id == g.id, Image.visibility == "active", ~exists(excluded_sq))
    images_total = (await db.execute(select(func.count()).select_from(Image).where(*visible))).scalar_one()
    images = (
        (
            await db.execute(
                select(Image)
                .where(*visible)
                .order_by(page_order)
                .offset((page - 1) * limit)
                .limit(limit)
                .options(selectinload(Image.blob))
            )
        )
        .scalars()
        .all()
    )
    thumbs = await existing_base_thumbs(img.blob_sha256 for img in images)
    return {
        "gallery": _trash_item(g, cover_map.get(g.id), users, merged),
        "media": {
            "total_size": stats["total_size"],
            "counts": {"image": stats["image_count"], "gif": stats["gif_count"], "video": stats["video_count"]},
        },
        "images": [
            {
                "id": img.id,
                "page_num": img.page_num,
                **_thumb_fields(img.blob, thumbs),
                "media_type": _media_type(img),
                "pending": _is_pending(img),
            }
            for img in images
        ],
        "images_total": images_total,
        "page": page,
    }
