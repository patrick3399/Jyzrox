"""Library split from routers/library.py (library_images_browse)."""

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ARRAY, Text, cast, desc, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from db.models import (
    BlockedTag,
    Gallery,
    Image,
    UserImageFavorite,
)
from services.cas import (
    existing_base_thumbs,
    image_file_url,
)
from services.gallery_sort import (
    IMAGE_ADDED_AT_SPEC,
    encode_value,
    keyset_after,
    order_by,
    parse_cursor_value,
)
from services.library_helpers import cursor_secret as _cursor_secret
from services.library_helpers import get_image_favorite_set as _get_image_favorite_set
from services.library_serializers import media_type as _media_type
from services.library_serializers import thumb_fields as _thumb_fields

router = APIRouter()


def _encode_image_cursor(img: Image) -> str:
    payload = json.dumps(
        {
            "added_at": encode_value(img.added_at),
            "id": img.id,
        }
    )
    sig = hmac.new(_cursor_secret(), payload.encode(), hashlib.sha256).hexdigest()
    raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{raw}.{sig}"


def _decode_image_cursor(cursor: str) -> dict:
    raw, _, sig = cursor.rpartition(".")
    if not raw or not sig:
        raise ValueError("bad cursor")
    padded = raw + "=" * (-len(raw) % 4)
    payload = base64.urlsafe_b64decode(padded)
    expected = hmac.new(_cursor_secret(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad sig")
    return json.loads(payload)


def _i_browse(img: Image, thumbs: set[str]) -> dict:
    blob = img.blob
    gallery = img.gallery
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        **_thumb_fields(blob, thumbs),
        "file_path": image_file_url(blob, img.external_path),
        "thumbhash": blob.thumbhash if blob else None,
        "media_type": _media_type(img),
        "added_at": img.added_at.isoformat() if img.added_at else None,
        "source": gallery.source if gallery else None,
        "source_id": gallery.source_id if gallery else None,
    }


async def _apply_image_filters(stmt, *, source, gallery_id, auth, db, category=None, favorited=None):
    """Apply common image browser filters (source, category, blocked tags, gallery access)."""
    stmt = stmt.where(gallery_access_filter(auth))
    stmt = stmt.where(Image.visibility == "active")
    # Pending link pages have no thumbnail or dimensions: keep them out of the
    # grid, the timeline scrubber and the time range alike.
    stmt = stmt.where(Image.blob_sha256.is_not(None))

    if gallery_id is not None:
        stmt = stmt.where(Image.gallery_id == gallery_id)
    if source is not None:
        # Support compound source filter like "local:link" → source="local", import_mode="link"
        colon_idx = source.find(":")
        if colon_idx != -1:
            stmt = stmt.where(Gallery.source == source[:colon_idx], Gallery.import_mode == source[colon_idx + 1 :])
        else:
            stmt = stmt.where(Gallery.source == source)
    if category is not None:
        if category == "__uncategorized__":
            stmt = stmt.where(or_(Gallery.category.is_(None), Gallery.category == ""))
        else:
            stmt = stmt.where(Gallery.category == category)
    # Blocked tags exclusion
    blocked_rows = (
        await db.execute(select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == auth["user_id"]))
    ).all()
    if blocked_rows:
        blocked_patterns = [f"{ns}:{name}" for ns, name in blocked_rows]
        stmt = stmt.where(not_(Gallery.tags_array.overlap(cast(blocked_patterns, ARRAY(Text)))))

    if favorited:
        stmt = stmt.where(
            exists(
                select(UserImageFavorite.image_id).where(
                    UserImageFavorite.user_id == auth["user_id"],
                    UserImageFavorite.image_id == Image.id,
                )
            )
        )

    return stmt


@router.get("/images/timeline_percentiles")
async def image_timeline_percentiles(
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    gallery_id: int | None = None,
    favorited: bool | None = Query(default=None),
    buckets: int = Query(default=100, le=200),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return percentile timestamps for the filtered image set.

    Returns ~buckets timestamps evenly distributed by image count,
    enabling count-based (not time-based) scrubber interpolation.
    Index 0 = newest, last index = oldest (matches scrubber convention
    where ratio 0 = top = newest, ratio 1 = bottom = oldest).
    """
    base = select(Image.added_at).join(Gallery, Image.gallery_id == Gallery.id)
    base = await _apply_image_filters(
        base,
        source=source,
        gallery_id=gallery_id,
        auth=auth,
        db=db,
        category=category,
        favorited=favorited,
    )
    base = base.where(Image.added_at.isnot(None))

    # Use NTILE window function to split images into N evenly-sized buckets
    # ordered newest-first so bucket 1 = newest, bucket N = oldest
    bucket_col = func.ntile(buckets).over(order_by=desc(Image.added_at)).label("bucket")
    sub = base.add_columns(bucket_col).subquery()

    stmt = select(sub.c.bucket, func.min(sub.c.added_at).label("ts")).group_by(sub.c.bucket).order_by(sub.c.bucket)

    rows = (await db.execute(stmt)).all()
    return {
        "timestamps": [row.ts.isoformat() for row in rows if row.ts],
        "total_buckets": len(rows),
    }


@router.get("/images/time_range")
async def image_time_range(
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    gallery_id: int | None = None,
    favorited: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return min/max added_at for the filtered image set."""
    stmt = select(func.min(Image.added_at), func.max(Image.added_at)).join(Gallery, Image.gallery_id == Gallery.id)
    stmt = await _apply_image_filters(
        stmt,
        source=source,
        gallery_id=gallery_id,
        auth=auth,
        db=db,
        category=category,
        favorited=favorited,
    )
    row = (await db.execute(stmt)).one()
    return {
        "min_at": row[0].isoformat() if row[0] else None,
        "max_at": row[1].isoformat() if row[1] else None,
    }


@router.get("/images")
async def browse_images(
    cursor: str | None = None,
    jump_at: str | None = None,
    limit: int = Query(default=40, le=100),
    sort: Literal["newest", "oldest"] = "newest",
    gallery_id: int | None = None,
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    favorited: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Cross-gallery image browser with cursor-based pagination."""
    if jump_at is not None and cursor is not None:
        raise HTTPException(400, "jump_at and cursor are mutually exclusive")

    stmt = (
        select(Image)
        .join(Gallery, Image.gallery_id == Gallery.id)
        .options(selectinload(Image.blob), selectinload(Image.gallery))
    )
    stmt = await _apply_image_filters(
        stmt,
        source=source,
        gallery_id=gallery_id,
        auth=auth,
        db=db,
        category=category,
        favorited=favorited,
    )

    # jump_at: seek to a specific timestamp anchor
    if jump_at is not None:
        try:
            jump_at_dt = datetime.fromisoformat(jump_at)
        except ValueError:
            raise HTTPException(400, "Invalid jump_at datetime format")
        if sort == "newest":
            stmt = stmt.where(Image.added_at <= jump_at_dt)
        else:
            stmt = stmt.where(Image.added_at >= jump_at_dt)

    # Sort direction (NULL added_at follows PostgreSQL's natural placement)
    direction = "desc" if sort == "newest" else "asc"
    order_cols = order_by(IMAGE_ADDED_AT_SPEC, Image.added_at, Image.id, direction)

    # Keyset cursor
    if cursor:
        try:
            cursor_data = _decode_image_cursor(cursor)
            raw_at = cursor_data.get("added_at")
            if raw_at is not None and not isinstance(raw_at, str):
                raise ValueError("bad added_at")
            cursor_at = parse_cursor_value(IMAGE_ADDED_AT_SPEC, raw_at)  # legacy "" -> NULL
            cursor_id = int(cursor_data["id"])
            stmt = stmt.where(
                keyset_after(IMAGE_ADDED_AT_SPEC, Image.added_at, Image.id, direction, cursor_at, cursor_id)
            )
        except Exception:
            raise HTTPException(400, "Invalid cursor")

    stmt = stmt.order_by(*order_cols).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()

    has_next = len(rows) > limit
    images_out = rows[:limit]

    next_cursor = None
    if has_next and images_out:
        last = images_out[-1]
        next_cursor = _encode_image_cursor(last)

    fav_ids = await _get_image_favorite_set(db, auth["user_id"], [img.id for img in images_out])
    thumbs = await existing_base_thumbs(img.blob_sha256 for img in images_out)

    return {
        "images": [_i_browse(img, thumbs) for img in images_out],
        "next_cursor": next_cursor,
        "has_next": has_next,
        "favorited_image_ids": sorted(fav_ids),
    }
