"""Explorer per-gallery image and history endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, case, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.auth import gallery_access_filter, has_gallery_write_access, require_auth, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from core.gallery_helpers import (
    image_not_excluded_clause,
)
from db.models import (
    Blob,
    Gallery,
    GalleryMetadataChange,
    GalleryMetadataFieldState,
    Image,
)
from services.cas import existing_base_thumbs, image_file_url, thumb_srcset, thumb_url
from services.explorer_requests import (
    PurgeImagesRequest,
)
from services.gallery_lifecycle import invalidate_sources_cache
from services.image_purge import purge_hidden_images
from services.media_formats import media_type_for_extension

router = APIRouter()
_member = require_role("member")


async def _load_visible_gallery(db: AsyncSession, gallery_id: int, auth: dict) -> Gallery:
    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return gallery


@router.get("/galleries/{gallery_id}/images")
async def list_gallery_images(
    gallery_id: int,
    visibility: Literal["active", "hidden", "all"] = Query(default="active"),
    media: Literal["all", "image", "video", "gif"] = Query(default="all"),
    sort: Literal["page", "size"] = Query(default="page"),
    direction: Literal["asc", "desc"] = Query(default="asc"),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=200, ge=1, le=500),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Paged, DB-backed image listing for one gallery in the Explorer.

    ``visibility=all`` means active plus user-hidden rows. Ordering for
    ``sort=page`` is active pages first (by ``page_num``), then hidden images by
    their original position (``source_position``, falling back to id); the
    direction flips the whole order. ``sort=size`` orders by blob size with
    blob-less (pending) rows last, ties broken by image id. ``media`` filters on
    the blob media type, so pending rows only appear under ``media=all``.
    """
    gallery = await _load_visible_gallery(db, gallery_id, auth)
    can_edit = await has_gallery_write_access(db, gallery.id, gallery.created_by_user_id, auth)

    visibilities = {"active": ("active",), "hidden": ("user_hidden",), "all": ("active", "user_hidden")}[visibility]
    # Same rule as /library: an ExcludedBlob hides *active* pages of its gallery.
    # Hidden rows stay listed so they can still be restored or purged.
    not_excluded = or_(Image.visibility != "active", image_not_excluded_clause())
    filters = [Image.gallery_id == gallery.id, Image.visibility.in_(visibilities), not_excluded]
    if media != "all":
        filters.append(Blob.media_type == media)

    total = (
        await db.execute(
            select(func.count(Image.id))
            .select_from(Image)
            .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
            .where(*filters)
        )
    ).scalar_one()

    other = aliased(Image)
    shared = exists(
        select(other.id).where(other.blob_sha256 == Image.blob_sha256, other.gallery_id != Image.gallery_id)
    ).label("shared")
    stmt = select(Image, Blob, shared).outerjoin(Blob, Blob.sha256 == Image.blob_sha256).where(*filters)
    direct = asc if direction == "asc" else desc
    if sort == "size":
        stmt = stmt.order_by(direct(Blob.file_size).nulls_last(), direct(Image.id))
    else:
        stmt = stmt.order_by(
            direct(case((Image.visibility == "active", 0), else_=1)),
            direct(
                case(
                    (Image.visibility == "active", Image.page_num), else_=func.coalesce(Image.source_position, Image.id)
                )
            ),
            direct(Image.id),
        )
    rows = (await db.execute(stmt.offset(offset).limit(limit))).all()
    thumbs = await existing_base_thumbs(blob.sha256 for _image, blob, _shared in rows if blob is not None)

    items = []
    for image, blob, is_shared in rows:
        has_thumb = blob is not None and blob.sha256 in thumbs
        hidden = image.visibility == "user_hidden"
        items.append(
            {
                "image_id": image.id,
                # Hidden rows store a negative sentinel page_num; expose none.
                "page_num": None if hidden else image.page_num,
                "source_position": image.source_position,
                "filename": image.filename,
                "visibility": "hidden" if hidden else "active",
                "hidden_at": image.hidden_at,
                "media_type": blob.media_type
                if blob is not None
                else (media_type_for_extension(image.filename or image.external_path or "") or "image"),
                "file_size": blob.file_size if blob is not None else None,
                "width": blob.width if blob is not None else None,
                "height": blob.height if blob is not None else None,
                "duration": blob.duration if blob is not None else None,
                "storage": (blob.storage or "cas") if blob is not None else "pending",
                "shared": bool(is_shared),
                "thumb_path": thumb_url(blob.sha256) if has_thumb else None,
                "thumb_srcset": thumb_srcset(blob.sha256) if has_thumb else None,
                "file_path": image_file_url(blob, image.external_path),
            }
        )

    summary_rows = (
        await db.execute(
            select(
                Image.visibility,
                func.count(Image.id).label("count"),
                func.coalesce(func.sum(Blob.file_size), 0).label("bytes"),
            )
            .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.gallery_id == gallery.id, Image.visibility.in_(("active", "user_hidden")), not_excluded)
            .group_by(Image.visibility)
        )
    ).all()
    by_visibility = {row.visibility: (int(row.count), int(row.bytes)) for row in summary_rows}

    others = aliased(Image)
    reclaimable_blobs = (
        select(Blob.sha256, Blob.file_size)
        .select_from(Image)
        .join(Blob, Blob.sha256 == Image.blob_sha256)
        .where(
            Image.gallery_id == gallery.id,
            Image.visibility == "user_hidden",
            Blob.storage == "cas",
            Image.external_path.is_(None),
            ~exists(
                select(others.id).where(
                    others.blob_sha256 == Blob.sha256,
                    or_(others.gallery_id != gallery.id, others.visibility != "user_hidden"),
                )
            ),
        )
        .distinct()
        .subquery()
    )
    reclaimable = (await db.execute(select(func.coalesce(func.sum(reclaimable_blobs.c.file_size), 0)))).scalar_one()

    return {
        "gallery_id": gallery.id,
        "source": gallery.source,
        "source_id": gallery.source_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "can_edit": can_edit,
        "summary": {
            "active_count": by_visibility.get("active", (0, 0))[0],
            "hidden_count": by_visibility.get("user_hidden", (0, 0))[0],
            "active_bytes": by_visibility.get("active", (0, 0))[1],
            "hidden_bytes": by_visibility.get("user_hidden", (0, 0))[1],
            "hidden_reclaimable_bytes": int(reclaimable or 0),
        },
        "items": items,
    }


@router.post("/galleries/{gallery_id}/images/purge")
async def purge_gallery_images(
    gallery_id: int,
    request: PurgeImagesRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete hidden images; ``dry_run`` previews without mutating."""
    result = await purge_hidden_images(
        db,
        gallery_id,
        None if request.all_hidden else request.image_ids,
        auth,
        dry_run=request.dry_run,
    )
    if not request.dry_run and (result["purged"] or result["blobs_deleted"]):
        await invalidate_sources_cache()
        await emit_safe(
            EventType.GALLERY_UPDATED,
            actor_user_id=auth["user_id"],
            resource_type="gallery",
            resource_id=gallery_id,
            action="images_purged",
            purged=result["purged"],
            reclaim_bytes=result["reclaim_bytes"],
        )
    return result


@router.get("/galleries/{gallery_id}/metadata-history")
async def metadata_history(
    gallery_id: int,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    from core.auth import gallery_access_filter
    from db.models import Gallery

    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")

    states = (
        (await db.execute(select(GalleryMetadataFieldState).where(GalleryMetadataFieldState.gallery_id == gallery_id)))
        .scalars()
        .all()
    )
    changes = (
        (
            await db.execute(
                select(GalleryMetadataChange)
                .where(GalleryMetadataChange.gallery_id == gallery_id)
                .order_by(desc(GalleryMetadataChange.created_at), desc(GalleryMetadataChange.id))
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return {
        "gallery_id": gallery_id,
        "fields": {
            state.field_name: {
                "origin": state.origin,
                "locked": state.locked,
                "source_value": state.source_value,
                "updated_at": state.updated_at,
            }
            for state in states
        },
        "changes": [
            {
                "id": change.id,
                "field": change.field_name,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "origin": change.origin,
                "actor_user_id": change.actor_user_id,
                "operation_id": str(change.operation_id) if change.operation_id else None,
                "created_at": change.created_at,
            }
            for change in changes
        ],
    }
