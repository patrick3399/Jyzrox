"""Library split from routers/library.py (library_artists)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from core.gallery_helpers import (
    build_cover_sha_map,
)
from core.utils import escape_like
from db.models import (
    Gallery,
    Image,
)
from services.cas import (
    existing_base_thumbs,
    image_file_url,
)
from services.cas import thumb_url as cas_thumb_url
from services.library_helpers import artist_display_name as _artist_display_name
from services.library_serializers import file_size as _file_size
from services.library_serializers import is_pending as _is_pending
from services.library_serializers import media_type as _media_type
from services.library_serializers import thumb_fields as _thumb_fields

_build_cover_sha_map = build_cover_sha_map
router = APIRouter()


@router.get("/artists")
async def list_artists(
    q: str = Query(default=""),
    source: str | None = Query(default=None),
    sort: Literal["gallery_count", "total_pages", "latest"] = Query(default="latest"),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List artists grouped from gallery artist_id field."""
    # Base query: group galleries by artist_id
    base = (
        select(
            Gallery.artist_id,
            func.max(Gallery.uploader).label("artist_name"),
            func.count().label("gallery_count"),
            func.coalesce(func.sum(Gallery.pages), 0).label("total_pages"),
            func.max(Gallery.added_at).label("latest_added_at"),
        )
        .where(Gallery.artist_id.is_not(None), gallery_access_filter(auth))
        .group_by(Gallery.artist_id)
    )

    if q:
        base = base.having(
            or_(
                func.max(Gallery.uploader).ilike(f"%{escape_like(q)}%", escape="\\"),
                Gallery.artist_id.ilike(f"%{escape_like(q)}%", escape="\\"),
            )
        )
    if source:
        base = base.where(Gallery.artist_id.startswith(f"{source}:"))

    # Count total
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Sort
    sort_col = {
        "gallery_count": desc(func.count()),
        "total_pages": desc(func.coalesce(func.sum(Gallery.pages), 0)),
        "latest": desc(func.max(Gallery.content_updated_at)),
    }[sort]
    base = base.order_by(sort_col).offset(page * limit).limit(limit)

    rows = (await db.execute(base)).all()

    # Fetch cover thumbs for each artist (most recent gallery's first image)
    artist_ids = [r.artist_id for r in rows]
    cover_map: dict[str, str | None] = {}
    if artist_ids:
        # Subquery: for each artist_id, get the gallery with the latest added_at
        latest_gallery_sub = (
            select(Gallery.id, Gallery.artist_id, Gallery.source)
            .where(Gallery.artist_id.in_(artist_ids))
            .order_by(Gallery.artist_id, desc(Gallery.added_at))
            .distinct(Gallery.artist_id)
        ).subquery()

        latest_rows = (
            await db.execute(
                select(latest_gallery_sub.c.id, latest_gallery_sub.c.artist_id, latest_gallery_sub.c.source)
            )
        ).all()
        latest_by_id = {row.id: row.artist_id for row in latest_rows}
        source_map = {row.id: row.source or "" for row in latest_rows}
        sha_map = await _build_cover_sha_map(db, list(latest_by_id.keys()), source_map)
        cover_map = {
            latest_by_id[gallery_id]: cas_thumb_url(sha256)
            for gallery_id, sha256 in sha_map.items()
            if gallery_id in latest_by_id
        }

    result = []
    for r in rows:
        aid = r.artist_id
        src = aid.split(":", 1)[0] if ":" in aid else ""
        result.append(
            {
                "artist_id": aid,
                "artist_name": _artist_display_name(aid, r.artist_name),
                "source": src,
                "gallery_count": r.gallery_count,
                "total_pages": r.total_pages,
                "cover_thumb": cover_map.get(aid),
                "latest_added_at": r.latest_added_at.isoformat() if r.latest_added_at else None,
            }
        )

    return {"artists": result, "total": total}


@router.get("/artists/{artist_id:path}/summary")
async def get_artist_summary(
    artist_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get summary info for a specific artist."""
    # Aggregate gallery-level fields
    agg_stmt = select(
        func.max(Gallery.uploader).label("artist_name"),
        func.count().label("gallery_count"),
        func.coalesce(func.sum(Gallery.pages), 0).label("total_pages"),
        func.max(Gallery.added_at).label("latest_added_at"),
    ).where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
    agg_row = (await db.execute(agg_stmt)).one_or_none()
    if not agg_row or agg_row.gallery_count == 0:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Count total images across all galleries for this artist
    total_images_stmt = (
        select(func.count(Image.id))
        .join(Gallery, Image.gallery_id == Gallery.id)
        .where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
    )
    total_images = (await db.execute(total_images_stmt)).scalar_one()

    # Cover thumb: most recent gallery's cover image (per-source page selection)
    latest_gallery_row = (
        await db.execute(
            select(Gallery.id, Gallery.source)
            .where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
            .order_by(desc(Gallery.added_at))
            .limit(1)
        )
    ).one_or_none()

    cover_thumb: str | None = None
    if latest_gallery_row:
        latest_gid = latest_gallery_row.id
        latest_source = latest_gallery_row.source or ""
        cover_sha256 = (await _build_cover_sha_map(db, [latest_gid], {latest_gid: latest_source})).get(latest_gid)
        cover_thumb = cas_thumb_url(cover_sha256) if cover_sha256 else None

    source = artist_id.split(":", 1)[0] if ":" in artist_id else ""

    return {
        "artist_id": artist_id,
        "artist_name": _artist_display_name(artist_id, agg_row.artist_name),
        "source": source,
        "gallery_count": agg_row.gallery_count,
        "total_pages": agg_row.total_pages,
        "total_images": total_images,
        "latest_added_at": agg_row.latest_added_at.isoformat() if agg_row.latest_added_at else None,
        "cover_thumb": cover_thumb,
    }


@router.get("/artists/{artist_id:path}/images")
async def list_artist_images(
    artist_id: str,
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=200),
    sort: Literal["newest", "oldest"] = Query(default="newest"),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all images across all galleries for a given artist, paginated."""
    # Verify the artist exists (at least one visible gallery with this artist_id)
    exists_stmt = select(func.count(Gallery.id)).where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
    artist_gallery_count = (await db.execute(exists_stmt)).scalar_one()
    if artist_gallery_count == 0:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Count total images for this artist
    total_stmt = (
        select(func.count(Image.id))
        .join(Gallery, Image.gallery_id == Gallery.id)
        .where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
    )
    total_count = (await db.execute(total_stmt)).scalar_one()

    # Main query: Image + Blob + Gallery for the given artist
    gallery_order = desc(Gallery.added_at) if sort == "newest" else asc(Gallery.added_at)
    stmt = (
        select(
            Image,
            Gallery.title.label("gallery_title"),
            Gallery.source.label("gallery_source"),
            Gallery.source_id.label("gallery_source_id"),
        )
        .join(Gallery, Image.gallery_id == Gallery.id)
        .where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
        .order_by(gallery_order, asc(Image.page_num))
        .offset(page * limit)
        .limit(limit)
        .options(selectinload(Image.blob))
    )
    rows = (await db.execute(stmt)).all()
    thumbs = await existing_base_thumbs(row[0].blob_sha256 for row in rows)

    images = []
    for row in rows:
        img: Image = row[0]
        gallery_title: str = row[1]
        gallery_source: str = row[2]
        gallery_source_id: str = row[3]
        blob = img.blob
        images.append(
            {
                "id": img.id,
                "gallery_id": img.gallery_id,
                "page_num": img.page_num,
                "filename": img.filename,
                "width": blob.width if blob else None,
                "height": blob.height if blob else None,
                "file_path": image_file_url(blob, img.external_path),
                **_thumb_fields(blob, thumbs),
                "file_size": _file_size(img),
                "file_hash": blob.sha256 if blob else None,
                "media_type": _media_type(img),
                "duration": blob.duration if blob else None,
                "pending": _is_pending(img),
                "gallery_title": gallery_title,
                "gallery_source": gallery_source,
                "gallery_source_id": gallery_source_id,
            }
        )

    return {
        "artist_id": artist_id,
        "images": images,
        "total": total_count,
        "page": page,
        "has_next": (page + 1) * limit < total_count,
    }
