"""Library split from routers/library.py (library_gallery_detail)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, exists, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.redis_client import get_redis
from core.source_display import get_display_config
from db.models import (
    ExcludedBlob,
    Gallery,
    GallerySourceItem,
    GalleryTag,
    Image,
    UserImageFavorite,
)
from services.cas import (
    existing_base_thumbs,
)
from services.library_helpers import get_image_favorite_set as _get_image_favorite_set
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source
from services.library_helpers import single_cover_thumb as _single_cover_thumb
from services.library_helpers import user_gallery_state as _user_gallery_state
from services.library_serializers import gallery_media_stats as _gallery_media_stats
from services.library_serializers import images_with_source_items as _images_with_source_items
from services.library_serializers import serialize_gallery as _g
from services.library_serializers import serialize_image as _i
from services.library_serializers import source_item_dict as _source_item_dict
from services.link_sync import LinkSyncResult, sync_link_gallery

_member = require_role("member")
router = APIRouter()


@router.get("/galleries/{source}/{source_id}")
async def get_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    cover_thumb = await _single_cover_thumb(db, g.id, g.source or "")
    is_fav, my_rating, in_rl = await _user_gallery_state(db, auth["user_id"], g.id)
    data = _g(g, cover_thumb=cover_thumb, is_favorited=is_fav, my_rating=my_rating, in_reading_list=in_rl)
    data["media_stats"] = await _gallery_media_stats(db, g.id)
    if g.source == "pixiv" and str(g.source_id).startswith("user:"):
        items = (
            (
                await db.execute(
                    select(GallerySourceItem)
                    .where(GallerySourceItem.gallery_id == g.id)
                    .order_by(GallerySourceItem.source_position.asc())
                )
            )
            .scalars()
            .all()
        )
        data["source_items"] = [_source_item_dict(item) for item in items]
    return data


@router.get("/galleries/{source}/{source_id}/images")
async def get_gallery_images(
    source: str,
    source_id: str,
    page: int | None = Query(default=None, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    display_cfg = get_display_config(g.source or "")
    page_order = desc(Image.page_num) if display_cfg.image_order == "desc" else asc(Image.page_num)
    excluded_sq = (
        select(ExcludedBlob.blob_sha256)
        .where(ExcludedBlob.gallery_id == gallery_id)
        .correlate(Image)
        .where(ExcludedBlob.blob_sha256 == Image.blob_sha256)
    )
    stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id)
        .where(Image.visibility == "active")
        .where(~exists(excluded_sq))
        .order_by(page_order)
        .options(selectinload(Image.blob))
    )

    # When limit is provided, return paginated response
    if limit is not None:
        p = page or 1
        total_stmt = select(func.count()).select_from(
            select(Image.id)
            .where(Image.gallery_id == gallery_id)
            .where(Image.visibility == "active")
            .where(~exists(excluded_sq))
            .subquery()
        )
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = stmt.offset((p - 1) * limit).limit(limit)
        images = (await db.execute(stmt)).scalars().all()

        fav_ids = await _get_image_favorite_set(db, auth["user_id"], [img.id for img in images])
        image_data = await _images_with_source_items(db, images)
        return {
            "gallery_id": gallery_id,
            "images": image_data,
            "total": total,
            "page": p,
            "has_next": (p * limit) < total,
            "favorited_image_ids": sorted(fav_ids),
        }

    # Default: return all images (backward compatible for Reader)
    images = (await db.execute(stmt)).scalars().all()
    fav_ids = await _get_image_favorite_set(db, auth["user_id"], [img.id for img in images])
    return {
        "gallery_id": gallery_id,
        "images": await _images_with_source_items(db, images),
        "favorited_image_ids": sorted(fav_ids),
    }


@router.post("/galleries/{source}/{source_id}/sync")
async def sync_gallery_with_source(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Reconcile a link-mode gallery with its folder before it is read.

    Anyone who can read the gallery may call this: the sync mirrors the folder
    on the system's behalf and is not a user edit (ADR 0014). The sync only
    stats files (ADR 0015); hashing the new pages is queued by the service.
    """
    g = await _get_or_404_by_source(db, source, source_id, auth)
    if g.import_mode != "link" or not g.source_path:
        return LinkSyncResult(status="not_link", pages=g.pages).as_dict()

    result = await sync_link_gallery(g.id, redis=get_redis())
    return result.as_dict()


@router.get("/galleries/{source}/{source_id}/hidden")
async def list_hidden_images(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List user-hidden images for a gallery."""
    g = await _get_or_404_by_source(db, source, source_id, auth)
    images = (
        (
            await db.execute(
                select(Image)
                .where(Image.gallery_id == g.id, Image.visibility == "user_hidden")
                .order_by(desc(Image.hidden_at), asc(Image.page_num))
                .options(selectinload(Image.blob))
            )
        )
        .scalars()
        .all()
    )
    fav_ids = await _get_image_favorite_set(db, auth["user_id"], [img.id for img in images])
    thumbs = await existing_base_thumbs(img.blob_sha256 for img in images)
    return {
        "gallery_id": g.id,
        "images": [_i(img, thumbs) for img in images],
        "favorited_image_ids": sorted(fav_ids),
    }


@router.post("/images/{image_id}/favorite")
async def favorite_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Add an image to the user's favorites."""
    img = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")

    stmt = (
        pg_insert(UserImageFavorite)
        .values(
            user_id=auth["user_id"],
            image_id=image_id,
        )
        .on_conflict_do_nothing()
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


@router.delete("/images/{image_id}/favorite")
async def unfavorite_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Remove an image from the user's favorites."""
    await db.execute(
        sa_delete(UserImageFavorite).where(
            UserImageFavorite.user_id == auth["user_id"],
            UserImageFavorite.image_id == image_id,
        )
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/galleries/{source}/{source_id}/tags")
async def get_gallery_tags(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get gallery tags with confidence scores and source info."""
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    rows = (
        (
            await db.execute(
                select(GalleryTag)
                .where(GalleryTag.gallery_id == gallery_id)
                .options(selectinload(GalleryTag.tag))
                .order_by(GalleryTag.confidence.desc())
            )
        )
        .scalars()
        .all()
    )

    tags = []
    for gt in rows:
        tag = gt.tag
        tags.append(
            {
                "namespace": tag.namespace,
                "name": tag.name,
                "confidence": gt.confidence,
                "source": gt.source,
            }
        )
    return {"gallery_id": gallery_id, "tags": tags}
