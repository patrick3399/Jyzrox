"""Local library CRUD — queries galleries/images tables via GIN index."""

import base64
import hashlib
import hmac
import json
import logging
import re as _re
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, asc, cast, desc, exists, func, not_, or_, select, tuple_
from sqlalchemy import case as sql_case
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import literal as sql_literal
from sqlalchemy.sql import text as sql_text

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.gallery_helpers import (
    build_cover_map,
    build_cover_sha_map,
    get_blocked_tag_strings,
    get_favorite_set,
    get_rating_map,
    get_reading_list_set,
)
from core.redis_client import get_redis
from core.source_display import get_display_config
from db.models import (
    Blob,
    BlockedTag,
    ExcludedBlob,
    Gallery,
    GalleryTag,
    Image,
    ReadProgress,
    Tag,
    UserFavorite,
    UserImageFavorite,
    UserRating,
    UserReadingList,
)
from plugins.builtin.ehentai.browse import _make_client as _make_eh_client
from plugins.builtin.gallery_dl._sites import get_site_config as _get_gdl_site_config
from services.cas import (
    cas_url,
    library_dir,
    thumb_dir,
)
from services.cas import thumb_url as cas_thumb_url
from services.gallery_lifecycle import (
    hard_delete_galleries as _hard_delete_galleries,
    invalidate_sources_cache as _invalidate_sources_cache,
)
from services.settings_store import get_toggle as _get_toggle

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])

_member = require_role("member")


def _artist_display_name(artist_id: str | None, uploader: str | None) -> str:
    """Return the user-facing artist name without conflating EH uploader data."""
    clean_uploader = (uploader or "").strip()
    if not artist_id:
        return clean_uploader

    source, _, raw_name = artist_id.partition(":")
    if source == "ehentai" and raw_name:
        return raw_name
    if clean_uploader:
        return clean_uploader
    return raw_name or artist_id


def _trash_filter(auth: dict):
    """Return WHERE clause for trash visibility: soft-deleted galleries the user can see."""
    filters = [Gallery.deleted_at.is_not(None)]
    if auth.get("role") != "admin":
        filters.append(
            or_(
                Gallery.created_by_user_id == auth["user_id"],
                Gallery.created_by_user_id.is_(None),
            )
        )
    return and_(*filters)


# ── Cursor helpers ────────────────────────────────────────────────────


def _cursor_secret() -> bytes:
    """Return the HMAC signing key for pagination cursors."""
    from core.keys import cursor_hmac_key

    return cursor_hmac_key()


def _encode_cursor(gallery: Gallery, sort: str) -> str:
    """Encode sort key + id into a signed URL-safe base64 cursor string.

    Format: <base64url(json)>.<hmac-sha256-hex>
    """
    sort_val = {
        "added_at": gallery.added_at.isoformat() if gallery.added_at else "",
        "rating": gallery.rating,
        "pages": gallery.pages if gallery.pages is not None else 0,
    }[sort]
    payload = {"id": gallery.id, "v": str(sort_val), "s": sort}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_cursor_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def _decode_cursor(cursor: str) -> dict:
    """Decode and verify a signed cursor. Raises HTTP 400 if invalid or tampered."""
    if "." not in cursor:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    # Split on the last dot so the base64 payload (which may contain dots in edge
    # cases due to padding) is kept intact; HMAC hex is always 64 hex chars.
    encoded, _, sig = cursor.rpartition(".")
    if not encoded or not sig:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    expected_sig = hmac.new(_cursor_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(status_code=400, detail="Invalid cursor: signature mismatch")
    try:
        # Re-add stripped padding before decoding.
        padded = encoded + "=" * (4 - len(encoded) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


# ── Gallery list ─────────────────────────────────────────────────────


# Backward-compat aliases — functions now live in core.gallery_helpers
_get_favorite_set = get_favorite_set
_get_reading_list_set = get_reading_list_set


async def _get_image_favorite_set(db: AsyncSession, user_id: int, image_ids: list[int]) -> set[int]:
    """Return set of image_ids that are favorited by this user."""
    if not image_ids:
        return set()
    result = await db.execute(
        select(UserImageFavorite.image_id).where(
            UserImageFavorite.user_id == user_id,
            UserImageFavorite.image_id.in_(image_ids),
        )
    )
    return {row[0] for row in result}


_get_rating_map = get_rating_map
_get_blocked_tag_strings = get_blocked_tag_strings
_build_cover_map = build_cover_map
_build_cover_sha_map = build_cover_sha_map


async def _single_cover_thumb(db: AsyncSession, gallery_id: int, source: str) -> str | None:
    """Get cover thumbnail for a single gallery."""
    cover_map = await _build_cover_map(db, [gallery_id], {gallery_id: source})
    return cover_map.get(gallery_id)


async def _user_gallery_state(db: AsyncSession, user_id: int, gallery_id: int) -> tuple[bool, int | None, bool]:
    """Return (is_favorited, my_rating, in_reading_list) for a user+gallery pair."""
    fav_row = await db.execute(
        select(UserFavorite).where(
            UserFavorite.user_id == user_id,
            UserFavorite.gallery_id == gallery_id,
        )
    )
    rating_row = await db.execute(
        select(UserRating.rating).where(
            UserRating.user_id == user_id,
            UserRating.gallery_id == gallery_id,
        )
    )
    rl_row = await db.execute(
        select(UserReadingList).where(
            UserReadingList.user_id == user_id,
            UserReadingList.gallery_id == gallery_id,
        )
    )
    return (
        fav_row.scalar_one_or_none() is not None,
        rating_row.scalar_one_or_none(),
        rl_row.scalar_one_or_none() is not None,
    )


_SOURCES_CACHE_KEY = "library:sources"
_SOURCES_CACHE_TTL = 300  # 5 minutes


@router.get("/galleries/sources")
async def list_gallery_sources(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct source values from the galleries table.

    Cached in Redis for 5 minutes to avoid repeated DB hits.
    """
    r = get_redis()
    cached = await r.get(_SOURCES_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)

    rows = (await db.execute(select(Gallery.source).where(Gallery.source.is_not(None)).distinct())).scalars().all()

    # Build source list with import_mode variants for 'local'
    sources: list[dict] = []
    for src in sorted(rows):
        if src == "local":
            # Check which import_modes exist
            modes = (
                (
                    await db.execute(
                        select(Gallery.import_mode)
                        .where(
                            Gallery.source == "local",
                            Gallery.import_mode.is_not(None),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            for mode in sorted(modes):
                sources.append({"value": f"local:{mode}", "label": f"local:{mode}"})
            if not modes:
                sources.append({"value": "local", "label": "local"})
        else:
            cfg = _get_gdl_site_config(src)
            label = cfg.name if cfg.source_id == src else src
            sources.append({"value": src, "label": label})

    await r.set(_SOURCES_CACHE_KEY, json.dumps(sources), ex=_SOURCES_CACHE_TTL)
    return sources


@router.get("/galleries/categories")
async def list_gallery_categories(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct non-empty category values from the galleries table."""
    result = await db.execute(
        select(Gallery.category)
        .where(Gallery.category.isnot(None), Gallery.category != "")
        .distinct()
        .order_by(Gallery.category)
    )
    return {"categories": [r[0] for r in result.all()]}


@router.get("/galleries")
async def list_galleries(
    q: str = Query(default=""),
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
    favorited: bool | None = Query(default=None),
    in_reading_list: bool | None = Query(default=None),
    min_rating: int | None = Query(default=None, ge=0, le=5),
    source: str | None = Query(default=None),
    artist: str | None = Query(default=None),
    import_mode: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    sort: Literal["added_at", "rating", "pages"] = Query(default="added_at"),
    cursor: str | None = Query(default=None),
    collection: int | None = Query(default=None),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Search local library.
    Tag filtering uses tags_array GIN index for performance:
      tags=character:rem&tags=general:blue_hair → AND
      exclude_tags=general:sketch              → NOT

    Supports two pagination modes:
      - cursor-based (preferred): pass cursor= from previous response's next_cursor.
        No COUNT(*), O(1) seek via compound index.
      - page-based (legacy): pass page= integer. Capped at page 500.
    """
    stmt = select(Gallery)

    # Data isolation: non-admin users only see own + system + public galleries
    stmt = stmt.where(gallery_access_filter(auth))

    # GIN array operations
    if tags:
        stmt = stmt.where(Gallery.tags_array.contains(tags))
    if exclude_tags:
        stmt = stmt.where(not_(Gallery.tags_array.overlap(exclude_tags)))
    if favorited is not None:
        if favorited:
            stmt = stmt.where(
                Gallery.id.in_(select(UserFavorite.gallery_id).where(UserFavorite.user_id == auth["user_id"]))
            )
    if in_reading_list is not None:
        if in_reading_list:
            stmt = stmt.where(
                Gallery.id.in_(select(UserReadingList.gallery_id).where(UserReadingList.user_id == auth["user_id"]))
            )
    if min_rating is not None:
        stmt = stmt.where(
            Gallery.id.in_(
                select(UserRating.gallery_id).where(
                    UserRating.user_id == auth["user_id"],
                    UserRating.rating >= min_rating,
                )
            )
        )
    if source:
        stmt = stmt.where(Gallery.source == source)
    if artist:
        stmt = stmt.where(Gallery.artist_id == artist)
    if import_mode:
        stmt = stmt.where(Gallery.import_mode == import_mode)
    if category:
        if category == "__uncategorized__":
            stmt = stmt.where(or_(Gallery.category.is_(None), Gallery.category == ""))
        else:
            stmt = stmt.where(Gallery.category == category)
    if q:
        stmt = stmt.where(Gallery.title.ilike(f"%{q}%"))
    if collection is not None:
        from db.models import CollectionGallery

        stmt = stmt.where(
            Gallery.id.in_(select(CollectionGallery.gallery_id).where(CollectionGallery.collection_id == collection))
        )

    # Filter out galleries containing blocked tags
    user_id = auth["user_id"]
    blocked_tags = await _get_blocked_tag_strings(db, user_id)
    if blocked_tags:
        stmt = stmt.where(not_(Gallery.tags_array.overlap(blocked_tags)))

    sort_col = {"added_at": Gallery.added_at, "rating": Gallery.rating, "pages": Gallery.pages}[sort]

    if cursor is not None:
        # Keyset pagination — no COUNT(*), no OFFSET
        c = _decode_cursor(cursor)
        if c.get("s") != sort:
            raise HTTPException(status_code=400, detail="Cursor sort key does not match current sort parameter")

        cursor_id = c["id"]
        cursor_val = c["v"]

        # For all supported sorts we use DESC order, so "next page" means
        # (sort_val, id) strictly less than cursor values (tie-break on id DESC).
        if sort == "added_at":
            from datetime import datetime as _dt

            try:
                parsed = _dt.fromisoformat(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.added_at < parsed,
                    and_(Gallery.added_at == parsed, Gallery.id < cursor_id),
                )
            )
        elif sort == "rating":
            try:
                cv = int(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.rating < cv,
                    and_(Gallery.rating == cv, Gallery.id < cursor_id),
                )
            )
        else:  # pages
            try:
                cv = int(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.pages < cv,
                    and_(Gallery.pages == cv, Gallery.id < cursor_id),
                )
            )

        stmt = stmt.order_by(desc(sort_col), desc(Gallery.id)).limit(limit + 1)
        rows = (await db.execute(stmt)).scalars().all()

        has_next = len(rows) > limit
        if has_next:
            rows = rows[:limit]

        next_cursor = _encode_cursor(rows[-1], sort) if has_next and rows else None

        gallery_ids = [g.id for g in rows]
        source_map = {g.id: g.source or "" for g in rows}
        cover_map = await _build_cover_map(db, gallery_ids, source_map)

        fav_set = await _get_favorite_set(db, auth["user_id"], gallery_ids)
        rating_map = await _get_rating_map(db, auth["user_id"], gallery_ids)
        rl_set = await _get_reading_list_set(db, auth["user_id"], gallery_ids)

        return {
            "galleries": [
                _g(
                    g,
                    cover_thumb=cover_map.get(g.id),
                    is_favorited=(g.id in fav_set),
                    my_rating=rating_map.get(g.id),
                    in_reading_list=(g.id in rl_set),
                )
                for g in rows
            ],
            "next_cursor": next_cursor,
            "has_next": has_next,
        }

    else:
        # Legacy page-based pagination — keep COUNT(*) for backward compat
        if page > 500:
            raise HTTPException(status_code=400, detail="Page depth exceeds limit. Use cursor= for deep pagination.")

        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = stmt.order_by(desc(sort_col), desc(Gallery.id)).offset(page * limit).limit(limit)
        galleries = (await db.execute(stmt)).scalars().all()

        gallery_ids = [g.id for g in galleries]
        source_map = {g.id: g.source or "" for g in galleries}
        cover_map = await _build_cover_map(db, gallery_ids, source_map)

        fav_set = await _get_favorite_set(db, auth["user_id"], gallery_ids)
        rating_map = await _get_rating_map(db, auth["user_id"], gallery_ids)
        rl_set = await _get_reading_list_set(db, auth["user_id"], gallery_ids)

        return {
            "total": total,
            "page": page,
            "galleries": [
                _g(
                    g,
                    cover_thumb=cover_map.get(g.id),
                    is_favorited=(g.id in fav_set),
                    my_rating=rating_map.get(g.id),
                    in_reading_list=(g.id in rl_set),
                )
                for g in galleries
            ],
        }


# ── Image cursor helpers ──────────────────────────────────────────────


def _encode_image_cursor(img: Image) -> str:
    payload = json.dumps(
        {
            "added_at": img.added_at.isoformat() if img.added_at else "",
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


def _i_browse(img: Image) -> dict:
    blob = img.blob
    gallery = img.gallery
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        "thumb_path": _thumb_url(blob),
        "file_path": _to_url(blob),
        "thumbhash": blob.thumbhash if blob else None,
        "media_type": blob.media_type if blob else "image",
        "added_at": img.added_at.isoformat() if img.added_at else None,
        "source": gallery.source if gallery else None,
        "source_id": gallery.source_id if gallery else None,
    }


# ── Image browser ─────────────────────────────────────────────────────


async def _apply_image_filters(
    stmt, *, tags, exclude_tags, source, gallery_id, auth, db, category=None, favorited=None
):
    """Apply common image browser filters (tags, source, category, blocked tags, gallery access)."""
    stmt = stmt.where(gallery_access_filter(auth))
    stmt = stmt.where(Image.visibility == "active")

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
    if tags:
        stmt = stmt.where(Image.tags_array.contains(cast(tags, ARRAY(Text))))
    if exclude_tags:
        stmt = stmt.where(not_(Image.tags_array.overlap(cast(exclude_tags, ARRAY(Text)))))

    # Blocked tags exclusion
    blocked_rows = (
        await db.execute(select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == auth["user_id"]))
    ).all()
    if blocked_rows:
        blocked_patterns = [f"{ns}:{name}" for ns, name in blocked_rows]
        stmt = stmt.where(not_(Image.tags_array.overlap(cast(blocked_patterns, ARRAY(Text)))))

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
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
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
        tags=tags,
        exclude_tags=exclude_tags,
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
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
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
        tags=tags,
        exclude_tags=exclude_tags,
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
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
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
        tags=tags,
        exclude_tags=exclude_tags,
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

    # Sort direction
    if sort == "newest":
        order_cols = [desc(Image.added_at), desc(Image.id)]
    else:
        order_cols = [asc(Image.added_at), asc(Image.id)]

    # Keyset cursor
    if cursor:
        try:
            cursor_data = _decode_image_cursor(cursor)
            cursor_at = datetime.fromisoformat(cursor_data["added_at"]) if cursor_data.get("added_at") else None
            cursor_id = cursor_data["id"]
            if sort == "newest":
                if cursor_at:
                    stmt = stmt.where(
                        or_(
                            Image.added_at < cursor_at,
                            and_(Image.added_at == cursor_at, Image.id < cursor_id),
                        )
                    )
                else:
                    stmt = stmt.where(Image.id < cursor_id)
            else:
                if cursor_at:
                    stmt = stmt.where(
                        or_(
                            Image.added_at > cursor_at,
                            and_(Image.added_at == cursor_at, Image.id > cursor_id),
                        )
                    )
                else:
                    stmt = stmt.where(Image.id > cursor_id)
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

    return {
        "images": [_i_browse(img) for img in images_out],
        "next_cursor": next_cursor,
        "has_next": has_next,
        "favorited_image_ids": sorted(fav_ids),
    }


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
                func.max(Gallery.uploader).ilike(f"%{q}%"),
                Gallery.artist_id.ilike(f"%{q}%"),
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
        "latest": desc(func.max(Gallery.added_at)),
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
                "file_path": _to_url(blob),
                "thumb_path": _thumb_url(blob),
                "file_size": blob.file_size if blob else None,
                "file_hash": blob.sha256 if blob else None,
                "media_type": blob.media_type if blob else "image",
                "duration": blob.duration if blob else None,
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


@router.get("/files")
async def list_files(
    q: str = Query(default=""),
    source: str | None = Query(default=None),
    import_mode: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List library galleries with image counts and size from DB metadata."""
    filters = [gallery_access_filter(auth)]
    if q:
        filters.append(Gallery.title.ilike(f"%{q}%"))
    if source:
        filters.append(Gallery.source == source)
    if import_mode:
        filters.append(Gallery.import_mode == import_mode)

    total = (await db.execute(select(func.count()).select_from(Gallery).where(*filters))).scalar_one()

    image_counts = func.count(Image.id).label("file_count")
    disk_size = func.coalesce(func.sum(Blob.file_size), 0).label("disk_size")
    stmt = (
        select(Gallery, image_counts, disk_size)
        .outerjoin(Image, Image.gallery_id == Gallery.id)
        .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
        .where(*filters)
        .group_by(Gallery.id)
        .order_by(Gallery.id.desc())
        .offset(page * limit)
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    paged_ids = [g.id for g, _, _ in rows]
    fav_set = await _get_favorite_set(db, auth["user_id"], paged_ids)
    rating_map = await _get_rating_map(db, auth["user_id"], paged_ids)

    result = []
    for g, file_count, total_size in rows:
        result.append(
            {
                "gallery_id": g.id,
                "source_id": g.source_id,
                "title": g.title,
                "category": g.category,
                "file_count": file_count,
                "rating": g.rating,
                "favorited": False,
                "is_favorited": g.id in fav_set,
                "my_rating": rating_map.get(g.id, 0),
                "source": g.source,
                "import_mode": g.import_mode,
                "artist_id": g.artist_id,
                "uploader": g.uploader,
                "library_path": g.library_path,
                "source_path": g.source_path,
                "disk_size": total_size,
            }
        )

    return {"directories": result, "total": total, "page": page}


@router.get("/files/{source}/{source_id}")
async def list_gallery_files(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all files inside a gallery's library directory with DB metadata."""
    import asyncio
    import os

    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    gdir = library_dir(g.source, g.source_id)

    def _scan_files() -> list[dict]:
        """Scan the gallery directory and return raw file info."""
        entries = []
        try:
            for entry in os.scandir(gdir):
                if not entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                    continue
                path = Path(entry.path)
                is_symlink = path.is_symlink()
                is_broken = is_symlink and not path.exists()
                symlink_target: str | None = None
                if is_symlink:
                    try:
                        symlink_target = os.readlink(path)
                    except OSError:
                        pass
                file_size: int | None = None
                if not is_broken:
                    try:
                        file_size = entry.stat(follow_symlinks=True).st_size
                    except OSError:
                        pass
                entries.append(
                    {
                        "filename": entry.name,
                        "file_size": file_size,
                        "is_symlink": is_symlink,
                        "is_broken": is_broken,
                        "symlink_target": symlink_target,
                    }
                )
        except OSError:
            pass
        return entries

    raw_files = await asyncio.to_thread(_scan_files)

    # Cross-reference with DB Image records by filename
    filenames = [f["filename"] for f in raw_files]
    img_map: dict[str, Image] = {}
    if filenames:
        img_stmt = (
            select(Image)
            .where(Image.gallery_id == gallery_id, Image.filename.in_(filenames))
            .options(selectinload(Image.blob))
        )
        db_images = (await db.execute(img_stmt)).scalars().all()
        img_map = {img.filename: img for img in db_images}

    files = []
    for f in sorted(raw_files, key=lambda x: x["filename"]):
        img = img_map.get(f["filename"])
        blob = img.blob if img else None
        files.append(
            {
                "filename": f["filename"],
                "page_num": img.page_num if img else None,
                "width": blob.width if blob else None,
                "height": blob.height if blob else None,
                "file_size": f["file_size"],
                "media_type": blob.media_type if blob else "image",
                "thumb_path": _thumb_url(blob),
                "file_path": _to_url(blob),
                "is_symlink": f["is_symlink"],
                "is_broken": f["is_broken"],
                "symlink_target": f["symlink_target"],
            }
        )

    return {
        "gallery_id": gallery_id,
        "source": g.source,
        "source_id": g.source_id,
        "title": g.title,
        "category": g.category,
        "files": files,
        "total_files": len(files),
    }


class BatchAction(BaseModel):
    action: Literal[
        "delete",
        "favorite",
        "unfavorite",
        "rate",
        "add_to_collection",
        "add_tags",
        "remove_tags",
        "add_to_reading_list",
        "remove_from_reading_list",
    ]
    gallery_ids: list[int]  # max 100
    rating: int | None = None  # required when action=rate
    collection_id: int | None = None  # required when action=add_to_collection
    tags: list[str] | None = None  # required when action=add_tags or remove_tags


@router.post("/galleries/batch")
async def batch_galleries(
    body: BatchAction,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Batch operations on multiple galleries."""
    if len(body.gallery_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 galleries per batch")
    if not body.gallery_ids:
        raise HTTPException(status_code=400, detail="No gallery IDs provided")
    if body.action == "rate" and (body.rating is None or body.rating < 0 or body.rating > 5):
        raise HTTPException(status_code=400, detail="Rating must be 0-5 for rate action")

    if body.action == "favorite":
        for gid in body.gallery_ids:
            stmt = (
                pg_insert(UserFavorite)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gid,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(body.gallery_ids)}

    elif body.action == "unfavorite":
        result = await db.execute(
            sa_delete(UserFavorite).where(
                UserFavorite.user_id == auth["user_id"],
                UserFavorite.gallery_id.in_(body.gallery_ids),
            )
        )
        await db.commit()
        return {"status": "ok", "affected": result.rowcount}

    elif body.action == "add_to_reading_list":
        for gid in body.gallery_ids:
            stmt = (
                pg_insert(UserReadingList)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gid,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(body.gallery_ids)}

    elif body.action == "remove_from_reading_list":
        result = await db.execute(
            sa_delete(UserReadingList).where(
                UserReadingList.user_id == auth["user_id"],
                UserReadingList.gallery_id.in_(body.gallery_ids),
            )
        )
        await db.commit()
        return {"status": "ok", "affected": result.rowcount}

    elif body.action == "rate":
        for gid in body.gallery_ids:
            if body.rating == 0:
                await db.execute(
                    sa_delete(UserRating).where(
                        UserRating.user_id == auth["user_id"],
                        UserRating.gallery_id == gid,
                    )
                )
            else:
                stmt = (
                    pg_insert(UserRating)
                    .values(
                        user_id=auth["user_id"],
                        gallery_id=gid,
                        rating=body.rating,
                    )
                    .on_conflict_do_update(
                        index_elements=["user_id", "gallery_id"],
                        set_={"rating": body.rating, "rated_at": func.now()},
                    )
                )
                await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(body.gallery_ids)}

    elif body.action == "add_to_collection":
        if body.collection_id is None:
            raise HTTPException(status_code=400, detail="collection_id required for add_to_collection")
        from db.models import Collection, CollectionGallery

        collection = await db.get(Collection, body.collection_id)
        if not collection or collection.user_id != auth["user_id"]:
            raise HTTPException(status_code=404, detail="Collection not found")

        max_pos_result = (
            await db.execute(
                select(func.coalesce(func.max(CollectionGallery.position), -1)).where(
                    CollectionGallery.collection_id == body.collection_id
                )
            )
        ).scalar_one()

        added = 0
        for i, gid in enumerate(body.gallery_ids):
            existing = (
                await db.execute(
                    select(CollectionGallery).where(
                        CollectionGallery.collection_id == body.collection_id,
                        CollectionGallery.gallery_id == gid,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue
            cg = CollectionGallery(
                collection_id=body.collection_id,
                gallery_id=gid,
                position=max_pos_result + 1 + i,
            )
            db.add(cg)
            added += 1

        collection.updated_at = datetime.now(UTC)
        await db.commit()
        return {"status": "ok", "affected": added}

    elif body.action == "add_tags":
        if not body.tags:
            raise HTTPException(status_code=400, detail="tags required for add_tags action")
        from worker.tag_helpers import parse_tag_strings, rebuild_gallery_tags_array

        parsed = parse_tag_strings(body.tags)
        if not parsed:
            return {"status": "ok", "affected": 0}

        # Upsert tags ONCE (count=0 to just ensure they exist without inflating counts)
        tag_values = [{"namespace": ns, "name": name, "count": 0} for ns, name in parsed]
        tag_stmt = (
            pg_insert(Tag)
            .values(tag_values)
            .on_conflict_do_nothing(index_elements=["namespace", "name"])
            .returning(Tag.id)
        )
        await db.execute(tag_stmt)

        # Resolve tag IDs in one query
        tag_ids = (await db.execute(select(Tag.id).where(tuple_(Tag.namespace, Tag.name).in_(parsed)))).scalars().all()

        if not tag_ids:
            return {"status": "ok", "affected": 0}

        # Upsert gallery_tags for ALL galleries at once
        gt_values = [
            {"gallery_id": gid, "tag_id": tid, "confidence": 1.0, "source": "manual"}
            for gid in body.gallery_ids
            for tid in tag_ids
        ]
        if gt_values:
            gt_stmt = (
                pg_insert(GalleryTag)
                .values(gt_values)
                .on_conflict_do_update(
                    index_elements=["gallery_id", "tag_id"],
                    set_={
                        "confidence": sql_case(
                            (GalleryTag.source == "metadata", GalleryTag.confidence),
                            else_=pg_insert(GalleryTag).excluded.confidence,
                        ),
                        "source": sql_case(
                            (GalleryTag.source == "metadata", GalleryTag.source),
                            else_=sql_literal("manual"),
                        ),
                    },
                )
            )
            await db.execute(gt_stmt)

        # Rebuild tags_array for each gallery
        for gid in body.gallery_ids:
            await rebuild_gallery_tags_array(db, gid)

        # Recalculate counts for affected tags (correct, not inflated)
        for tid in tag_ids:
            count_result = await db.execute(select(func.count()).where(GalleryTag.tag_id == tid))
            actual_count = count_result.scalar_one()
            await db.execute(Tag.__table__.update().where(Tag.id == tid).values(count=actual_count))

        await db.commit()
        return {"status": "ok", "affected": len(body.gallery_ids)}

    elif body.action == "remove_tags":
        if not body.tags:
            raise HTTPException(status_code=400, detail="tags required for remove_tags action")
        from worker.tag_helpers import parse_tag_strings, rebuild_gallery_tags_array

        parsed = parse_tag_strings(body.tags)
        if not parsed:
            return {"status": "ok", "affected": 0}

        # Resolve tag IDs once
        ns_name_filter = or_(*[(Tag.namespace == ns) & (Tag.name == name) for ns, name in parsed])
        tag_ids = (await db.execute(select(Tag.id).where(ns_name_filter))).scalars().all()

        if not tag_ids:
            return {"status": "ok", "affected": 0}

        # Bulk delete gallery_tags across all galleries in one statement
        del_result = await db.execute(
            sa_delete(GalleryTag).where(
                GalleryTag.gallery_id.in_(body.gallery_ids),
                GalleryTag.tag_id.in_(tag_ids),
                GalleryTag.source == "manual",
            )
        )
        removed = del_result.rowcount

        # Recalculate counts for affected tags
        for tid in tag_ids:
            count_result = await db.execute(select(func.count()).where(GalleryTag.tag_id == tid))
            actual_count = count_result.scalar_one()
            await db.execute(Tag.__table__.update().where(Tag.id == tid).values(count=actual_count))

        # Rebuild tags_array for each gallery
        for gid in body.gallery_ids:
            await rebuild_gallery_tags_array(db, gid)

        await db.commit()
        return {"status": "ok", "affected": removed}

    elif body.action == "delete":
        return await _batch_delete_galleries(db, body.gallery_ids, auth)


async def _batch_delete_galleries(db: AsyncSession, gallery_ids: list[int], auth: dict) -> dict:
    """Soft-delete multiple galleries by setting deleted_at timestamp."""
    # Load all galleries
    stmt = select(Gallery).where(Gallery.id.in_(gallery_ids))
    galleries = (await db.execute(stmt)).scalars().all()
    if not galleries:
        return {"status": "ok", "affected": 0, "deleted_dirs": 0}

    for g in galleries:
        _check_write_access(auth, g)

    # Filter out galleries with active downloads (skip rather than reject for batch)
    from db.models import DownloadJob

    active_gallery_ids_result = await db.execute(
        select(DownloadJob.gallery_id).where(
            DownloadJob.gallery_id.in_([g.id for g in galleries]),
            DownloadJob.status.in_(["queued", "running", "paused"]),
        )
    )
    active_gallery_ids = set(active_gallery_ids_result.scalars().all())
    skip_ids = active_gallery_ids
    if skip_ids:
        galleries = [g for g in galleries if g.id not in skip_ids]
        if not galleries:
            return {"status": "ok", "affected": 0, "deleted_dirs": 0, "skipped": len(skip_ids)}

    now = datetime.now(UTC)
    for g in galleries:
        g.deleted_at = now
    await db.commit()
    await _invalidate_sources_cache()
    return {"status": "ok", "affected": len(galleries), "deleted_dirs": 0}


# ── Trash endpoints ───────────────────────────────────────────────────


@router.get("/trash/count")
async def trash_count(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return count of soft-deleted galleries."""
    trash_cond = _trash_filter(auth)
    count = (await db.execute(select(func.count()).select_from(Gallery).where(trash_cond))).scalar_one()
    return {"count": count}


@router.get("/trash")
async def list_trash(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List soft-deleted galleries (trash)."""
    trash_cond = _trash_filter(auth)

    count_result = await db.execute(select(func.count()).select_from(Gallery).where(trash_cond))
    total = count_result.scalar_one()

    rows = (
        (
            await db.execute(
                select(Gallery).where(trash_cond).order_by(desc(Gallery.deleted_at)).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return {
        "total": total,
        "galleries": [_g(g) for g in rows],
    }


@router.post("/galleries/{source}/{source_id}/restore")
async def restore_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore a soft-deleted gallery from trash."""
    source_id = unquote(source_id)
    g = (
        await db.execute(
            select(Gallery).where(
                Gallery.source == source,
                Gallery.source_id == source_id,
                Gallery.deleted_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")
    _check_write_access(auth, g)
    g.deleted_at = None
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.GALLERY_RESTORED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=g.id
    )
    return {"status": "ok"}


@router.post("/galleries/{source}/{source_id}/permanent-delete")
async def permanent_delete_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a gallery (from trash). Irreversible."""
    source_id = unquote(source_id)
    g = (
        await db.execute(
            select(Gallery).where(
                Gallery.source == source,
                Gallery.source_id == source_id,
                Gallery.deleted_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")
    _check_write_access(auth, g)
    result = await _hard_delete_galleries(db, [g])
    return {"status": "ok", **result}


@router.post("/trash/empty")
async def empty_trash(
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete all galleries in trash."""
    trash_cond = _trash_filter(auth)

    galleries = (await db.execute(select(Gallery).where(trash_cond))).scalars().all()

    if not galleries:
        return {"status": "ok", "affected": 0}

    result = await _hard_delete_galleries(db, galleries)
    return {"status": "ok", **result}


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
    return _g(g, cover_thumb=cover_thumb, is_favorited=is_fav, my_rating=my_rating, in_reading_list=in_rl)


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
        return {
            "gallery_id": gallery_id,
            "images": [_i(img) for img in images],
            "total": total,
            "page": p,
            "has_next": (p * limit) < total,
            "favorited_image_ids": sorted(fav_ids),
        }

    # Default: return all images (backward compatible for Reader)
    images = (await db.execute(stmt)).scalars().all()
    fav_ids = await _get_image_favorite_set(db, auth["user_id"], [img.id for img in images])
    return {"gallery_id": gallery_id, "images": [_i(img) for img in images], "favorited_image_ids": sorted(fav_ids)}


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
    return {"gallery_id": g.id, "images": [_i(img) for img in images], "favorited_image_ids": sorted(fav_ids)}


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


# ── Gallery update ───────────────────────────────────────────────────


class GalleryPatch(BaseModel):
    favorited: bool | None = None
    rating: int | None = None
    in_reading_list: bool | None = None
    title: str | None = None
    title_jpn: str | None = None
    category: str | None = None


@router.patch("/galleries/{source}/{source_id}")
async def update_gallery(
    source: str,
    source_id: str,
    patch: GalleryPatch,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    _check_write_access(auth, g)
    if patch.favorited is not None:
        if patch.favorited:
            stmt = (
                pg_insert(UserFavorite)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        else:
            await db.execute(
                sa_delete(UserFavorite).where(
                    UserFavorite.user_id == auth["user_id"],
                    UserFavorite.gallery_id == gallery_id,
                )
            )
    if patch.rating is not None:
        if patch.rating == 0:
            await db.execute(
                sa_delete(UserRating).where(
                    UserRating.user_id == auth["user_id"],
                    UserRating.gallery_id == gallery_id,
                )
            )
        else:
            stmt = (
                pg_insert(UserRating)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                    rating=patch.rating,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "gallery_id"],
                    set_={"rating": patch.rating, "rated_at": func.now()},
                )
            )
            await db.execute(stmt)
    if patch.in_reading_list is not None:
        if patch.in_reading_list:
            stmt = (
                pg_insert(UserReadingList)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        else:
            await db.execute(
                sa_delete(UserReadingList).where(
                    UserReadingList.user_id == auth["user_id"],
                    UserReadingList.gallery_id == gallery_id,
                )
            )
    if patch.title is not None:
        g.title = patch.title
    if patch.title_jpn is not None:
        g.title_jpn = patch.title_jpn
    if patch.category is not None:
        g.category = patch.category
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.GALLERY_UPDATED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=gallery_id
    )
    # Fetch updated per-user state to return accurate response
    is_fav, my_rating, in_rl = await _user_gallery_state(db, auth["user_id"], gallery_id)
    return _g(g, is_favorited=is_fav, my_rating=my_rating, in_reading_list=in_rl)


@router.delete("/galleries/{source}/{source_id}")
async def delete_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a gallery by setting deleted_at timestamp.

    The gallery is moved to trash and can be restored or permanently deleted later.
    A GC worker will permanently delete galleries that have been in trash longer
    than the configured retention period.
    """
    g = await _get_or_404_by_source(db, source, source_id, auth)
    _check_write_access(auth, g)

    from db.models import DownloadJob

    active_job = (
        await db.execute(
            select(DownloadJob.id)
            .where(
                DownloadJob.gallery_id == g.id,
                DownloadJob.status.in_(["queued", "running", "paused"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job:
        raise HTTPException(
            status_code=409, detail="Cannot delete gallery with active download job. Cancel the download first."
        )

    # Check if trash is enabled
    trash_enabled = await _get_toggle("setting:trash_enabled", True)

    if not trash_enabled:
        # Hard-delete immediately when trash is disabled
        result = await _hard_delete_galleries(db, [g])
        await _invalidate_sources_cache()
        return {"status": "ok", **result}

    g.deleted_at = datetime.now(UTC)
    await db.commit()
    await _invalidate_sources_cache()
    from core.events import EventType, emit_safe

    await emit_safe(EventType.GALLERY_DELETED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=g.id)
    return {"status": "ok", "deleted_files": 0}


class DeleteImageBody(BaseModel):
    page_num: int


async def _active_image_count(db: AsyncSession, gallery_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Image).where(Image.gallery_id == gallery_id, Image.visibility == "active")
        )
    ).scalar_one()


async def _compact_active_image_pages(db: AsyncSession, gallery_id: int) -> int:
    images = (
        (
            await db.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id, Image.visibility == "active")
                .order_by(asc(Image.page_num), asc(Image.id))
            )
        )
        .scalars()
        .all()
    )
    if all(img.page_num == index for index, img in enumerate(images, start=1)):
        return len(images)

    for img in images:
        img.page_num = -int(img.id)
    await db.flush()

    for index, img in enumerate(images, start=1):
        img.page_num = index
    await db.flush()
    return len(images)


async def _hide_image_row(db: AsyncSession, gallery: Gallery, img: Image) -> int:
    if img.visibility != "active":
        return await _active_image_count(db, gallery.id)

    if img.source_position is None:
        img.source_position = img.page_num
    img.visibility = "user_hidden"
    img.hidden_at = datetime.now(UTC)
    img.page_num = -int(img.id)
    await db.flush()
    active_count = await _compact_active_image_pages(db, gallery.id)
    gallery.pages = active_count
    return active_count


async def _restore_image_row(db: AsyncSession, gallery: Gallery, img: Image) -> int:
    if img.visibility != "user_hidden":
        return await _active_image_count(db, gallery.id)

    active_images = (
        (
            await db.execute(
                select(Image)
                .where(Image.gallery_id == gallery.id, Image.visibility == "active")
                .order_by(asc(Image.page_num), asc(Image.id))
            )
        )
        .scalars()
        .all()
    )
    if img.source_position is None:
        target_page = len(active_images) + 1
    else:
        target_page = 1 + sum(
            1
            for active in active_images
            if (active.source_position if active.source_position is not None else active.page_num) < img.source_position
        )

    moving_images = [(active, active.page_num) for active in active_images if active.page_num >= target_page]
    for active, _old_page in moving_images:
        active.page_num = -int(active.id)
    await db.flush()

    for active, old_page in moving_images:
        active.page_num = old_page + 1
    img.page_num = target_page
    img.visibility = "active"
    img.hidden_at = None
    await db.flush()

    active_count = len(active_images) + 1
    gallery.pages = active_count
    return active_count


@router.post("/galleries/{source}/{source_id}/delete-image")
async def delete_gallery_image(
    source: str,
    source_id: str,
    body: DeleteImageBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Hide a single image from a gallery by page number.

    This legacy endpoint used to delete the Image row and block the blob from
    re-import. It now preserves local data and marks the image as user_hidden
    so accidental hides can be restored immediately.
    """

    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = gallery.id
    _check_write_access(auth, gallery)

    img_stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id, Image.page_num == body.page_num, Image.visibility == "active")
        .options(selectinload(Image.blob))
    )
    img = (await db.execute(img_stmt)).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")

    remaining_pages = await _hide_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "remaining_pages": remaining_pages}


@router.post("/images/{image_id}/hide")
async def hide_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Hide an image without deleting local data."""
    img = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
            .options(selectinload(Image.gallery))
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    gallery = img.gallery
    _check_write_access(auth, gallery)
    remaining_pages = await _hide_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "remaining_pages": remaining_pages}


@router.post("/images/{image_id}/restore")
async def restore_hidden_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore a user-hidden image immediately."""
    img = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
            .options(selectinload(Image.gallery))
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    gallery = img.gallery
    _check_write_access(auth, gallery)
    remaining_pages = await _restore_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "remaining_pages": remaining_pages}


# ── Read progress ────────────────────────────────────────────────────


@router.get("/galleries/{source}/{source_id}/progress")
async def get_progress(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    prog = await db.get(ReadProgress, (auth["user_id"], gallery_id))
    if not prog:
        return {"gallery_id": gallery_id, "last_page": 0, "last_read_at": None}
    return {
        "gallery_id": gallery_id,
        "last_page": prog.last_page,
        "last_read_at": prog.last_read_at.isoformat() if prog.last_read_at else None,
    }


class ProgressBody(BaseModel):
    last_page: int


@router.post("/galleries/{source}/{source_id}/progress")
async def save_progress(
    source: str,
    source_id: str,
    body: ProgressBody,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    now = datetime.now(UTC)
    stmt = (
        pg_insert(ReadProgress)
        .values(user_id=auth["user_id"], gallery_id=gallery_id, last_page=body.last_page, last_read_at=now)
        .on_conflict_do_update(
            index_elements=["user_id", "gallery_id"],
            set_={"last_page": body.last_page, "last_read_at": now},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


# ── Similar images ───────────────────────────────────────────────────


def _hamming_neighbors_all(quarters: list[int], max_dist: int) -> list[set[int]]:
    """Generate all 16-bit signed integer neighbors within Hamming distance max_dist for each quarter.

    For max_dist=0: 1 value per quarter (exact match only)
    For max_dist=1: 17 values per quarter (C(16,0) + C(16,1))
    For max_dist=2: 137 values per quarter (C(16,0) + C(16,1) + C(16,2))
    """
    result = []
    for q_val in quarters:
        uval = q_val & 0xFFFF
        neighbors: set[int] = set()
        for dist in range(max_dist + 1):
            if dist == 0:
                neighbors.add(q_val)
            else:
                for bits in combinations(range(16), dist):
                    flipped = uval
                    for b in bits:
                        flipped ^= 1 << b
                    signed = flipped - 0x10000 if flipped >= 0x8000 else flipped
                    neighbors.add(signed)
        result.append(neighbors)
    return result


@router.get("/images/{image_id}/similar")
async def find_similar_images(
    image_id: int,
    threshold: int = Query(default=10, ge=0, le=32),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Find visually similar images by perceptual hash Hamming distance.

    Uses pigeonhole pre-filter on pHash quarter columns for indexed lookup,
    then exact Hamming distance on candidates. At 10M images, pre-filter
    returns ~1K-10K candidates instead of scanning all rows.
    Threshold 0 = exact match, 10 = visually similar (recommended default),
    32 = very loose match.
    """
    img_row = (
        await db.execute(select(Image).where(Image.id == image_id).options(selectinload(Image.blob)))
    ).scalar_one_or_none()
    if not img_row:
        raise HTTPException(status_code=404, detail="Image not found")
    if not img_row.blob or not img_row.blob.phash:
        raise HTTPException(status_code=400, detail="Image has no perceptual hash")

    phash = img_row.blob.phash
    phash_int_val = int(phash, 16)

    def _to_signed16(v: int) -> int:
        return v - 0x10000 if v >= 0x8000 else v

    quarters = [
        _to_signed16((phash_int_val >> 48) & 0xFFFF),
        _to_signed16((phash_int_val >> 32) & 0xFFFF),
        _to_signed16((phash_int_val >> 16) & 0xFFFF),
        _to_signed16(phash_int_val & 0xFFFF),
    ]

    max_quarter_dist = threshold // 4  # floor(T/4) — pigeonhole guarantee

    if max_quarter_dist > 2 or threshold > 11:
        # For loose thresholds the neighbor sets become large (>137 per quarter);
        # fall back to full scan on phash_int with exact bit_count filter.
        stmt = sql_text("""
            SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                   b.storage, b.external_path, b.phash,
                   bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
            FROM images i
            JOIN blobs b ON i.blob_sha256 = b.sha256
            WHERE b.phash_int IS NOT NULL
              AND i.id != :image_id
              AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
            ORDER BY distance ASC
            LIMIT :limit
        """)
        results = (
            await db.execute(
                stmt,
                {
                    "phash_int": phash_int_val,
                    "image_id": image_id,
                    "threshold": threshold,
                    "limit": limit,
                },
            )
        ).all()
    else:
        # Phase 1: generate Hamming neighborhoods for each quarter
        neighbors = _hamming_neighbors_all(quarters, max_quarter_dist)

        # Guard: if the combined neighbor sets are too large the ANY() arrays
        # become counterproductive — fall back to the full scan path instead.
        total_neighbors = sum(len(s) for s in neighbors)
        if total_neighbors > 10000:
            stmt = sql_text("""
                SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                       b.storage, b.external_path, b.phash,
                       bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
                ORDER BY distance ASC
                LIMIT :limit
            """)
            results = (
                await db.execute(
                    stmt,
                    {
                        "phash_int": phash_int_val,
                        "image_id": image_id,
                        "threshold": threshold,
                        "limit": limit,
                    },
                )
            ).all()
        else:
            # Phase 2: indexed pre-filter — OR across all four quarter columns,
            # then exact bit_count check on the surviving candidates only.
            conditions = []
            params: dict = {
                "image_id": image_id,
                "phash_int": phash_int_val,
                "threshold": threshold,
                "limit": limit,
            }
            for qi, neighbor_set in enumerate(neighbors):
                param_name = f"q{qi}_neighbors"
                conditions.append(f"b.phash_q{qi} = ANY(:{param_name})")
                params[param_name] = list(neighbor_set)

            where_prefilter = " OR ".join(conditions)

            stmt = sql_text(f"""
                SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                       b.storage, b.external_path, b.phash,
                       bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND ({where_prefilter})
                  AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
                ORDER BY distance ASC
                LIMIT :limit
            """)
            results = (await db.execute(stmt, params)).all()

    def _row_to_url(r) -> str:
        if r.storage == "external" and r.external_path:
            return r.external_path.replace("/mnt/", "/media/libraries/", 1)
        return cas_url(r.sha256, r.extension)

    return {
        "image_id": image_id,
        "phash": phash,
        "similar": [
            {
                "id": r.id,
                "gallery_id": r.gallery_id,
                "filename": r.filename,
                "file_path": _row_to_url(r),
                "thumb_path": cas_thumb_url(r.sha256),
                "phash": r.phash,
                "distance": r.distance,
            }
            for r in results
        ],
    }


# ── Excluded Blobs ───────────────────────────────────────────────────


@router.get("/galleries/{source}/{source_id}/excluded")
async def list_excluded_blobs(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List excluded blob hashes for a gallery."""
    from db.models import ExcludedBlob

    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    result = await db.execute(
        select(ExcludedBlob).where(ExcludedBlob.gallery_id == gallery_id).order_by(ExcludedBlob.excluded_at.desc())
    )
    blobs = result.scalars().all()
    return {
        "gallery_id": gallery_id,
        "excluded": [
            {"blob_sha256": b.blob_sha256, "excluded_at": b.excluded_at.isoformat() if b.excluded_at else None}
            for b in blobs
        ],
    }


@router.delete("/galleries/{source}/{source_id}/excluded/{sha256}")
async def restore_excluded_blob(
    source: str,
    source_id: str,
    sha256: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Remove a blob from the exclusion list (un-exclude)."""
    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = gallery.id
    _check_write_access(auth, gallery)
    from db.models import ExcludedBlob

    result = await db.execute(
        select(ExcludedBlob).where(
            ExcludedBlob.gallery_id == gallery_id,
            ExcludedBlob.blob_sha256 == sha256,
        )
    )
    blob = result.scalar_one_or_none()
    if not blob:
        raise HTTPException(status_code=404, detail="Excluded blob not found")
    await db.delete(blob)
    await db.commit()
    return {"status": "ok"}


@router.post("/galleries/{source}/{source_id}/check-update")
async def check_gallery_update(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Auto-check and update gallery metadata from source."""
    g = await _get_or_404_by_source(db, source, source_id, auth)

    if source == "ehentai":
        return await _check_update_ehentai(g, db, auth)
    if source == "pixiv":
        return await _check_update_pixiv(g, db, auth)
    return {"status": "skipped", "reason": "unsupported_source"}


async def _check_update_ehentai(g, db: AsyncSession, auth: dict) -> dict:
    """Fetch fresh EH metadata and update gallery record."""
    if not g.source_url:
        return {"status": "skipped", "reason": "no_source_url"}

    match = _re.search(r"/g/(\d+)/([a-f0-9]+)/", g.source_url)
    if not match:
        return {"status": "skipped", "reason": "no_source_url"}

    gid, token = int(match.group(1)), match.group(2)

    try:
        async with await _make_eh_client() as client:
            meta = await client.get_gallery_metadata(gid, token)
    except ValueError as exc:
        err_msg = str(exc)
        if "expunged" in err_msg.lower():
            g.metadata_updated_at = func.now()
            await db.commit()
            await db.refresh(g)
            return {"status": "expunged"}
        return {"status": "error", "reason": "invalid_metadata"}
    except Exception:
        return {"status": "error", "reason": "fetch_failed"}

    old = {
        "title": g.title,
        "title_jpn": g.title_jpn,
        "category": g.category,
        "uploader": g.uploader,
        "pages": g.pages,
        "rating": g.rating,
        "tags_array": list(g.tags_array or []),
    }

    if meta.get("title") is not None:
        g.title = meta["title"]
    if meta.get("title_jpn") is not None:
        g.title_jpn = meta["title_jpn"]
    if meta.get("category") is not None:
        g.category = meta["category"]
    if meta.get("uploader") is not None:
        g.uploader = meta["uploader"]
    if meta.get("pages") is not None:
        g.pages = meta["pages"]
    if meta.get("rating") is not None:
        g.rating = int(round(meta["rating"]))
    if meta.get("tags"):
        g.tags_array = meta["tags"]

    changed_fields = [
        f for f in ("title", "title_jpn", "category", "uploader", "pages", "rating") if getattr(g, f) != old[f]
    ]
    if list(g.tags_array or []) != old["tags_array"]:
        changed_fields.append("tags")

    pages_diff = {"old": old["pages"], "new": g.pages} if "pages" in changed_fields else None

    g.metadata_updated_at = func.now()
    await db.commit()
    await db.refresh(g)

    if not changed_fields:
        return {"status": "unchanged"}

    return await _build_updated_response(g, db, auth, changed_fields, pages_diff)


async def _check_update_pixiv(g, db: AsyncSession, auth: dict) -> dict:
    """Fetch fresh Pixiv illust metadata and update gallery record."""
    from services.credential import get_credential
    from services.pixiv_client import PixivClient

    refresh_token = await get_credential("pixiv")
    if not refresh_token:
        return {"status": "skipped", "reason": "credentials_required"}

    try:
        illust_id = int(g.source_id)
    except ValueError, TypeError:
        return {"status": "skipped", "reason": "invalid_source_id"}

    try:
        async with PixivClient(refresh_token=refresh_token) as client:
            detail = await client.illust_detail(illust_id)
    except Exception:
        return {"status": "error", "reason": "fetch_failed"}

    old_pages = g.pages
    new_pages = detail.get("page_count", 1)

    pages_diff = None
    changed_fields = []
    if new_pages != old_pages:
        g.pages = new_pages
        changed_fields.append("pages")
        pages_diff = {"old": old_pages, "new": new_pages}

    g.metadata_updated_at = func.now()
    await db.commit()
    await db.refresh(g)

    if not changed_fields:
        return {"status": "unchanged"}

    return await _build_updated_response(g, db, auth, changed_fields, pages_diff)


async def _build_updated_response(
    g, db: AsyncSession, auth: dict, changed_fields: list, pages_diff: dict | None
) -> dict:
    cover_thumb = await _single_cover_thumb(db, g.id, g.source or "")
    is_fav, my_rating, in_rl = await _user_gallery_state(db, auth["user_id"], g.id)
    return {
        "status": "updated",
        "gallery": _g(g, cover_thumb, is_fav, my_rating, in_reading_list=in_rl),
        "changed_fields": changed_fields,
        "pages_diff": pages_diff,
    }


# ── Helpers ──────────────────────────────────────────────────────────


def _to_url(blob) -> str | None:
    """Convert a Blob ORM object to its nginx-served URL."""
    if not blob:
        return None
    if blob.storage == "external" and blob.external_path:
        return blob.external_path.replace("/mnt/", "/media/libraries/", 1)
    return cas_url(blob.sha256, blob.extension)


def _thumb_url(blob) -> str | None:
    """Return the 160px thumbnail URL for a blob."""
    if not blob or not blob.sha256:
        return None
    if not (thumb_dir(blob.sha256) / "thumb_160.webp").exists():
        return None
    return cas_thumb_url(blob.sha256)


async def _get_or_404_by_source(db: AsyncSession, source: str, source_id: str, auth: dict | None = None) -> Gallery:
    """Fetch a gallery by (source, source_id) with optional access filter. Raises 404 if not found."""
    source_id = unquote(source_id)
    if auth is not None:
        stmt = select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
            gallery_access_filter(auth),
        )
        g = (await db.execute(stmt)).scalar_one_or_none()
    else:
        stmt = select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
        )
        g = (await db.execute(stmt)).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return g


def _check_write_access(auth: dict, gallery: Gallery) -> None:
    """Raise 403 if the caller cannot modify this gallery.

    Admins can modify any gallery. Members can modify galleries they created
    or unowned (legacy) galleries whose created_by_user_id is NULL.
    """
    if auth["role"] == "admin":
        return
    if gallery.created_by_user_id is None or gallery.created_by_user_id == auth["user_id"]:
        return
    raise HTTPException(status_code=403, detail="You do not have permission to modify this gallery")


def _g(
    g: Gallery,
    cover_thumb: str | None = None,
    is_favorited: bool = False,
    my_rating: int | None = None,
    in_reading_list: bool = False,
) -> dict:
    display_cfg = get_display_config(g.source or "")
    return {
        "id": g.id,
        "source": g.source,
        "source_id": g.source_id,
        "title": g.title,
        "title_jpn": g.title_jpn,
        "category": g.category,
        "language": g.language,
        "pages": g.pages,
        "posted_at": g.posted_at.isoformat() if g.posted_at else None,
        "added_at": g.added_at.isoformat() if g.added_at else None,
        "rating": g.rating,
        "favorited": False,
        "is_favorited": is_favorited,
        "my_rating": my_rating,
        "in_reading_list": in_reading_list,
        "uploader": g.uploader,
        "artist_id": g.artist_id,
        "artist_name": _artist_display_name(g.artist_id, g.uploader),
        "download_status": g.download_status,
        "import_mode": g.import_mode,
        "tags_array": g.tags_array or [],
        "cover_thumb": cover_thumb,
        "source_url": g.source_url,
        "source_path": g.source_path,
        "display_order": display_cfg.image_order,
        "metadata_updated_at": g.metadata_updated_at.isoformat() if g.metadata_updated_at else None,
    }


def _i(img: Image) -> dict:
    blob = img.blob
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "filename": img.filename,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        "file_path": _to_url(blob),
        "thumb_path": _thumb_url(blob),
        "file_size": blob.file_size if blob else None,
        "file_hash": blob.sha256 if blob else None,
        "media_type": blob.media_type if blob else "image",
        "duration": blob.duration if blob else None,
        "thumbhash": blob.thumbhash if blob else None,
        "visibility": img.visibility,
        "source_item_id": img.source_item_id,
        "source_item_url": img.source_item_url,
        "source_position": img.source_position,
        "source_seen_at": img.source_seen_at.isoformat() if img.source_seen_at else None,
        "hidden_at": img.hidden_at.isoformat() if img.hidden_at else None,
    }
