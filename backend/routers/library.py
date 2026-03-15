"""Local library CRUD — queries galleries/images tables via GIN index."""

import base64
import hashlib
import hmac
import json
import logging
import re as _re
import sqlite3
from datetime import UTC, datetime
from itertools import combinations
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, asc, case as sql_case, cast, delete as sa_delete, desc, func, not_, or_, select, tuple_
from sqlalchemy.sql import literal as sql_literal
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth, require_role
from core.config import settings
from core.database import get_db
from core.redis_client import get_redis
from core.source_display import get_display_config
from db.models import Blob, BlockedTag, Gallery, GalleryTag, Image, ReadProgress, Tag, UserFavorite, UserRating
from services.cas import cas_url, create_library_symlink, decrement_ref_count, library_dir, resolve_blob_path, safe_source_id, thumb_dir, thumb_url as cas_thumb_url
from plugins.builtin.ehentai.browse import _make_client as _make_eh_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])

_member = require_role("member")


def _trash_filter(auth: dict):
    """Return WHERE clause for trash visibility: soft-deleted galleries the user can see."""
    filters = [Gallery.deleted_at.is_not(None)]
    if auth.get("role") != "admin":
        filters.append(or_(
            Gallery.created_by_user_id == auth["user_id"],
            Gallery.created_by_user_id.is_(None),
        ))
    return and_(*filters)


def _cleanup_archive_entries(archive_keys: list[str]) -> None:
    """Remove entries from gallery-dl.db so deleted galleries can be re-downloaded."""
    from pathlib import Path as _Path
    archive_path = _Path(settings.data_archive_path) / "gallery-dl.db"
    if not archive_path.exists() or not archive_keys:
        return
    conn = sqlite3.connect(str(archive_path))
    try:
        conn.executemany("DELETE FROM archive WHERE entry = ?", [(k,) for k in archive_keys])
        conn.commit()
    finally:
        conn.close()


# ── Cursor helpers ────────────────────────────────────────────────────


def _cursor_secret() -> bytes:
    """Return the HMAC signing key derived from the app's credential_encrypt_key."""
    return settings.credential_encrypt_key.encode()


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


async def _get_favorite_set(db: AsyncSession, user_id: int, gallery_ids: list[int]) -> set[int]:
    """Return set of gallery_ids that are favorited by this user."""
    if not gallery_ids:
        return set()
    result = await db.execute(
        select(UserFavorite.gallery_id).where(
            UserFavorite.user_id == user_id,
            UserFavorite.gallery_id.in_(gallery_ids),
        )
    )
    return {row[0] for row in result}


async def _get_rating_map(db: AsyncSession, user_id: int, gallery_ids: list[int]) -> dict[int, int]:
    """Return {gallery_id: rating} for this user."""
    if not gallery_ids:
        return {}
    result = await db.execute(
        select(UserRating.gallery_id, UserRating.rating).where(
            UserRating.user_id == user_id,
            UserRating.gallery_id.in_(gallery_ids),
        )
    )
    return {row[0]: row[1] for row in result}


async def _get_blocked_tag_strings(db: AsyncSession, user_id: int) -> list[str]:
    """Return list of 'namespace:name' blocked tag strings for the user."""
    rows = (
        await db.execute(
            select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id)
        )
    ).all()
    return [f"{r.namespace}:{r.name}" for r in rows]


async def _build_cover_map(
    db: AsyncSession,
    gallery_ids: list[int],
    source_map: dict[int, str] | None = None,
) -> dict[int, str]:
    """Build gallery_id -> cover_thumb_url map, respecting per-source cover_page config.

    Args:
        db: Database session.
        gallery_ids: Gallery IDs to fetch covers for.
        source_map: Optional {gallery_id: source} mapping. If None, all use page_num=1.
    """
    if not gallery_ids:
        return {}

    # Split galleries by cover strategy
    first_ids: list[int] = []
    last_ids: list[int] = []
    for gid in gallery_ids:
        source = (source_map or {}).get(gid, "")
        cfg = get_display_config(source)
        if cfg.cover_page == "last":
            last_ids.append(gid)
        else:
            first_ids.append(gid)

    cover_map: dict[int, str] = {}

    # Batch query: first page covers
    if first_ids:
        stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .where(Image.gallery_id.in_(first_ids), Image.page_num == 1)
        )
        for r in (await db.execute(stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)

    # Batch query: last page covers
    if last_ids:
        max_page_sub = (
            select(Image.gallery_id, func.max(Image.page_num).label("max_page"))
            .where(Image.gallery_id.in_(last_ids))
            .group_by(Image.gallery_id)
        ).subquery()
        stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .join(
                max_page_sub,
                and_(
                    Image.gallery_id == max_page_sub.c.gallery_id,
                    Image.page_num == max_page_sub.c.max_page,
                ),
            )
        )
        for r in (await db.execute(stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)

    return cover_map


async def _single_cover_thumb(db: AsyncSession, gallery_id: int, source: str) -> str | None:
    """Get cover thumbnail for a single gallery."""
    cover_map = await _build_cover_map(db, [gallery_id], {gallery_id: source})
    return cover_map.get(gallery_id)


async def _user_gallery_state(db: AsyncSession, user_id: int, gallery_id: int) -> tuple[bool, int | None]:
    """Return (is_favorited, my_rating) for a user+gallery pair."""
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
    return (fav_row.scalar_one_or_none() is not None, rating_row.scalar_one_or_none())


_SOURCES_CACHE_KEY = "library:sources"
_SOURCES_CACHE_TTL = 300  # 5 minutes


async def _invalidate_sources_cache() -> None:
    """Delete the cached sources list so next request re-queries."""
    try:
        await get_redis().delete(_SOURCES_CACHE_KEY)
    except Exception:
        pass


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

    rows = (await db.execute(
        select(Gallery.source).where(Gallery.source.is_not(None)).distinct()
    )).scalars().all()

    # Build source list with import_mode variants for 'local'
    sources: list[dict] = []
    for src in sorted(rows):
        if src == "local":
            # Check which import_modes exist
            modes = (await db.execute(
                select(Gallery.import_mode).where(
                    Gallery.source == "local",
                    Gallery.import_mode.is_not(None),
                ).distinct()
            )).scalars().all()
            for mode in sorted(modes):
                sources.append({"value": f"local:{mode}", "label": f"local:{mode}"})
            if not modes:
                sources.append({"value": "local", "label": "local"})
        else:
            sources.append({"value": src, "label": src})

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
                Gallery.id.in_(
                    select(UserFavorite.gallery_id).where(UserFavorite.user_id == auth["user_id"])
                )
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
            Gallery.id.in_(
                select(CollectionGallery.gallery_id).where(CollectionGallery.collection_id == collection)
            )
        )

    # Filter out galleries containing blocked tags
    user_id = auth["user_id"]
    blocked_tags = await _get_blocked_tag_strings(db, user_id)
    if blocked_tags:
        stmt = stmt.where(not_(Gallery.tags_array.overlap(cast(blocked_tags, ARRAY(Text)))))

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

        return {
            "galleries": [
                _g(g, cover_thumb=cover_map.get(g.id), is_favorited=(g.id in fav_set), my_rating=rating_map.get(g.id))
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

        return {
            "total": total,
            "page": page,
            "galleries": [
                _g(g, cover_thumb=cover_map.get(g.id), is_favorited=(g.id in fav_set), my_rating=rating_map.get(g.id))
                for g in galleries
            ],
        }


# ── Image cursor helpers ──────────────────────────────────────────────


def _encode_image_cursor(img: Image) -> str:
    payload = json.dumps({
        "added_at": img.added_at.isoformat() if img.added_at else "",
        "id": img.id,
    })
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


async def _apply_image_filters(stmt, *, tags, exclude_tags, source, gallery_id, auth, db, category=None):
    """Apply common image browser filters (tags, source, category, blocked tags, gallery access)."""
    stmt = stmt.where(gallery_access_filter(auth))

    if gallery_id is not None:
        stmt = stmt.where(Image.gallery_id == gallery_id)
    if source is not None:
        # Support compound source filter like "local:link" → source="local", import_mode="link"
        colon_idx = source.find(":")
        if colon_idx != -1:
            stmt = stmt.where(Gallery.source == source[:colon_idx], Gallery.import_mode == source[colon_idx + 1:])
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
    blocked_rows = (await db.execute(
        select(BlockedTag.namespace, BlockedTag.name)
        .where(BlockedTag.user_id == auth["user_id"])
    )).all()
    if blocked_rows:
        blocked_patterns = [f"{ns}:{name}" for ns, name in blocked_rows]
        stmt = stmt.where(not_(Image.tags_array.overlap(cast(blocked_patterns, ARRAY(Text)))))

    return stmt


@router.get("/images/timeline_percentiles")
async def image_timeline_percentiles(
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    gallery_id: int | None = None,
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
        base, tags=tags, exclude_tags=exclude_tags, source=source,
        gallery_id=gallery_id, auth=auth, db=db, category=category,
    )
    base = base.where(Image.added_at.isnot(None))

    # Use NTILE window function to split images into N evenly-sized buckets
    # ordered newest-first so bucket 1 = newest, bucket N = oldest
    bucket_col = func.ntile(buckets).over(order_by=desc(Image.added_at)).label("bucket")
    sub = base.add_columns(bucket_col).subquery()

    stmt = (
        select(sub.c.bucket, func.min(sub.c.added_at).label("ts"))
        .group_by(sub.c.bucket)
        .order_by(sub.c.bucket)
    )

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
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_auth),
):
    """Return min/max added_at for the filtered image set."""
    stmt = (
        select(func.min(Image.added_at), func.max(Image.added_at))
        .join(Gallery, Image.gallery_id == Gallery.id)
    )
    stmt = await _apply_image_filters(
        stmt, tags=tags, exclude_tags=exclude_tags, source=source,
        gallery_id=gallery_id, auth=auth, db=db, category=category,
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
        stmt, tags=tags, exclude_tags=exclude_tags, source=source,
        gallery_id=gallery_id, auth=auth, db=db, category=category,
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

    return {
        "images": [_i_browse(img) for img in images_out],
        "next_cursor": next_cursor,
        "has_next": has_next,
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
    base = select(
        Gallery.artist_id,
        func.max(Gallery.uploader).label("artist_name"),
        func.count().label("gallery_count"),
        func.coalesce(func.sum(Gallery.pages), 0).label("total_pages"),
        func.max(Gallery.added_at).label("latest_added_at"),
    ).where(Gallery.artist_id.is_not(None), gallery_access_filter(auth)).group_by(Gallery.artist_id)

    if q:
        base = base.having(func.max(Gallery.uploader).ilike(f"%{q}%"))
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

        # First page covers
        first_cover_stmt = (
            select(latest_gallery_sub.c.artist_id, latest_gallery_sub.c.source, Blob.sha256)
            .join(Image, Image.gallery_id == latest_gallery_sub.c.id)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .where(Image.page_num == 1)
        )
        first_covers = {
            r.artist_id: (r.source, r.sha256)
            for r in (await db.execute(first_cover_stmt)).all()
        }

        # Last page covers
        max_page_sub = (
            select(Image.gallery_id, func.max(Image.page_num).label("max_page"))
            .where(Image.gallery_id.in_(select(latest_gallery_sub.c.id)))
            .group_by(Image.gallery_id)
        ).subquery()
        last_cover_stmt = (
            select(latest_gallery_sub.c.artist_id, latest_gallery_sub.c.source, Blob.sha256)
            .join(Image, Image.gallery_id == latest_gallery_sub.c.id)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .join(max_page_sub, and_(
                Image.gallery_id == max_page_sub.c.gallery_id,
                Image.page_num == max_page_sub.c.max_page,
            ))
        )
        last_covers = {
            r.artist_id: (r.source, r.sha256)
            for r in (await db.execute(last_cover_stmt)).all()
        }

        cover_map = {}
        for artist_id_val in first_covers.keys() | last_covers.keys():
            source_val = (first_covers.get(artist_id_val) or last_covers.get(artist_id_val, ("", "")))[0]
            cfg = get_display_config(source_val or "")
            if cfg.cover_page == "last" and artist_id_val in last_covers:
                cover_map[artist_id_val] = cas_thumb_url(last_covers[artist_id_val][1])
            elif artist_id_val in first_covers:
                cover_map[artist_id_val] = cas_thumb_url(first_covers[artist_id_val][1])

    result = []
    for r in rows:
        aid = r.artist_id
        src = aid.split(":", 1)[0] if ":" in aid else ""
        result.append({
            "artist_id": aid,
            "artist_name": r.artist_name or "",
            "source": src,
            "gallery_count": r.gallery_count,
            "total_pages": r.total_pages,
            "cover_thumb": cover_map.get(aid),
            "latest_added_at": r.latest_added_at.isoformat() if r.latest_added_at else None,
        })

    return {"artists": result, "total": total}


@router.get("/artists/{artist_id:path}/summary")
async def get_artist_summary(
    artist_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get summary info for a specific artist."""
    # Aggregate gallery-level fields
    agg_stmt = (
        select(
            func.max(Gallery.uploader).label("artist_name"),
            func.count().label("gallery_count"),
            func.coalesce(func.sum(Gallery.pages), 0).label("total_pages"),
            func.max(Gallery.added_at).label("latest_added_at"),
        )
        .where(Gallery.artist_id == artist_id, gallery_access_filter(auth))
    )
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
        display_cfg = get_display_config(latest_source)
        if display_cfg.cover_page == "last":
            cover_page_sub = (
                select(func.max(Image.page_num))
                .where(Image.gallery_id == latest_gid)
                .scalar_subquery()
            )
            cover_sha256 = (
                await db.execute(
                    select(Blob.sha256)
                    .join(Image, Image.blob_sha256 == Blob.sha256)
                    .where(Image.gallery_id == latest_gid, Image.page_num == cover_page_sub)
                    .limit(1)
                )
            ).scalar_one_or_none()
        else:
            cover_sha256 = (
                await db.execute(
                    select(Blob.sha256)
                    .join(Image, Image.blob_sha256 == Blob.sha256)
                    .where(Image.gallery_id == latest_gid, Image.page_num == 1)
                    .limit(1)
                )
            ).scalar_one_or_none()
        cover_thumb = cas_thumb_url(cover_sha256) if cover_sha256 else None

    source = artist_id.split(":", 1)[0] if ":" in artist_id else ""

    return {
        "artist_id": artist_id,
        "artist_name": agg_row.artist_name or "",
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
    gallery_order = (
        desc(Gallery.added_at) if sort == "newest" else asc(Gallery.added_at)
    )
    stmt = (
        select(Image, Gallery.title.label("gallery_title"), Gallery.source.label("gallery_source"), Gallery.source_id.label("gallery_source_id"))
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
        images.append({
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
        })

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
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List gallery directories under data_library_path with DB metadata."""
    import asyncio
    import os
    from pathlib import Path

    base = Path(settings.data_library_path)

    def _scan_dirs() -> list[tuple[str, str, int, int]]:
        """Return list of (source, source_id, file_count, disk_size) from two-level library tree."""
        entries = []
        try:
            for source_entry in os.scandir(base):
                if not source_entry.is_dir():
                    continue
                source = source_entry.name
                for sid_entry in os.scandir(source_entry.path):
                    if not sid_entry.is_dir():
                        continue
                    sid = sid_entry.name
                    file_count = 0
                    disk_size = 0
                    try:
                        for f in os.scandir(sid_entry.path):
                            if f.is_file(follow_symlinks=True):
                                file_count += 1
                                try:
                                    disk_size += f.stat(follow_symlinks=True).st_size
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    entries.append((source, sid, file_count, disk_size))
        except OSError:
            pass
        return entries

    raw_entries = await asyncio.to_thread(_scan_dirs)

    if not raw_entries:
        return {"directories": [], "total": 0, "page": page}

    fs_keys = [(e[0], e[1]) for e in raw_entries]
    size_map = {(e[0], e[1]): (e[2], e[3]) for e in raw_entries}

    from sqlalchemy import tuple_
    stmt = select(Gallery).where(tuple_(Gallery.source, Gallery.source_id).in_(fs_keys))
    if q:
        stmt = stmt.where(Gallery.title.ilike(f"%{q}%"))

    galleries = (await db.execute(stmt)).scalars().all()
    total = len(galleries)

    # Sort by gallery id descending (most recently added first)
    galleries = sorted(galleries, key=lambda g: g.id, reverse=True)
    paged = galleries[page * limit : (page + 1) * limit]

    paged_ids = [g.id for g in paged]
    fav_set = await _get_favorite_set(db, auth["user_id"], paged_ids)
    rating_map = await _get_rating_map(db, auth["user_id"], paged_ids)

    result = []
    for g in paged:
        file_count, disk_size = size_map.get((g.source, g.source_id), (0, 0))
        result.append({
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
            "disk_size": disk_size,
        })

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
    from pathlib import Path

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
                entries.append({
                    "filename": entry.name,
                    "file_size": file_size,
                    "is_symlink": is_symlink,
                    "is_broken": is_broken,
                    "symlink_target": symlink_target,
                })
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
        files.append({
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
        })

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
    action: Literal["delete", "favorite", "unfavorite", "rate", "add_to_collection", "add_tags", "remove_tags"]
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
            stmt = pg_insert(UserFavorite).values(
                user_id=auth["user_id"], gallery_id=gid,
            ).on_conflict_do_nothing()
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
                stmt = pg_insert(UserRating).values(
                    user_id=auth["user_id"], gallery_id=gid, rating=body.rating,
                ).on_conflict_do_update(
                    index_elements=["user_id", "gallery_id"],
                    set_={"rating": body.rating, "rated_at": func.now()},
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
                select(func.coalesce(func.max(CollectionGallery.position), -1))
                .where(CollectionGallery.collection_id == body.collection_id)
            )
        ).scalar_one()

        added = 0
        for i, gid in enumerate(body.gallery_ids):
            existing = (
                await db.execute(
                    select(CollectionGallery)
                    .where(
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
        tag_ids = (
            await db.execute(
                select(Tag.id).where(
                    tuple_(Tag.namespace, Tag.name).in_(parsed)
                )
            )
        ).scalars().all()

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
            count_result = await db.execute(
                select(func.count()).where(GalleryTag.tag_id == tid)
            )
            actual_count = count_result.scalar_one()
            await db.execute(
                Tag.__table__.update().where(Tag.id == tid).values(count=actual_count)
            )

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
        ns_name_filter = or_(
            *[(Tag.namespace == ns) & (Tag.name == name) for ns, name in parsed]
        )
        tag_ids = (
            await db.execute(select(Tag.id).where(ns_name_filter))
        ).scalars().all()

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
            count_result = await db.execute(
                select(func.count()).where(GalleryTag.tag_id == tid)
            )
            actual_count = count_result.scalar_one()
            await db.execute(
                Tag.__table__.update().where(Tag.id == tid).values(count=actual_count)
            )

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
            DownloadJob.status.in_(["queued", "running"]),
        )
    )
    active_gallery_ids = set(active_gallery_ids_result.scalars().all())
    downloading_ids = {g.id for g in galleries if g.download_status == "downloading"}
    skip_ids = active_gallery_ids | downloading_ids
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


async def _hard_delete_galleries(db: AsyncSession, galleries: list) -> dict:
    """Permanently delete galleries: decrement blob refs, remove DB records, cleanup filesystem."""
    import asyncio
    import shutil

    if not galleries:
        return {"affected": 0, "deleted_dirs": 0}

    # Load all images with blobs
    img_stmt = (
        select(Image)
        .where(Image.gallery_id.in_([g.id for g in galleries]))
        .options(selectinload(Image.blob))
    )
    images = (await db.execute(img_stmt)).scalars().all()

    blob_sha256s = [img.blob_sha256 for img in images]

    gallery_source_map = {g.id: g.source for g in galleries}
    archive_keys = [
        f"{gallery_source_map.get(img.gallery_id, '')}{img.filename}"
        for img in images if img.filename
    ]

    for sha256 in blob_sha256s:
        await decrement_ref_count(sha256, db)

    for g in galleries:
        await db.delete(g)
    await db.commit()

    await _invalidate_sources_cache()

    zero_ref_sha256s: set[str] = set()
    if blob_sha256s:
        zero_ref_result = await db.execute(
            select(Blob.sha256).where(Blob.sha256.in_(blob_sha256s), Blob.ref_count <= 0)
        )
        zero_ref_sha256s = set(zero_ref_result.scalars().all())

    def _delete_filesystem() -> int:
        deleted = 0
        for g in galleries:
            lib_dir = library_dir(g.source, g.source_id)
            if lib_dir.exists():
                try:
                    shutil.rmtree(str(lib_dir), ignore_errors=True)
                    deleted += 1
                except OSError as exc:
                    logger.warning("[hard_delete] failed to remove library dir %s: %s", lib_dir, exc)
        # Thumbnail cleanup — once, not per gallery
        for sha256 in zero_ref_sha256s:
            td = thumb_dir(sha256)
            if td.exists():
                try:
                    shutil.rmtree(str(td), ignore_errors=True)
                    deleted += 1
                except OSError as exc:
                    logger.warning("[hard_delete] failed to remove thumb dir %s: %s", td, exc)
        return deleted

    try:
        deleted_count = await asyncio.to_thread(_delete_filesystem)
    except Exception as exc:
        logger.warning("[hard_delete] cleanup failed: %s", exc)
        deleted_count = 0

    if archive_keys:
        try:
            await asyncio.to_thread(_cleanup_archive_entries, archive_keys)
        except Exception as exc:
            logger.warning("[hard_delete] archive cleanup failed: %s", exc)

    return {"affected": len(galleries), "deleted_dirs": deleted_count}


# ── Trash endpoints ───────────────────────────────────────────────────


@router.get("/trash/count")
async def trash_count(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return count of soft-deleted galleries."""
    trash_cond = _trash_filter(auth)
    count = (await db.execute(
        select(func.count()).select_from(Gallery).where(trash_cond)
    )).scalar_one()
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

    count_result = await db.execute(
        select(func.count()).select_from(Gallery).where(trash_cond)
    )
    total = count_result.scalar_one()

    rows = (await db.execute(
        select(Gallery).where(trash_cond).order_by(desc(Gallery.deleted_at)).limit(limit).offset(offset)
    )).scalars().all()

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
    g = (await db.execute(
        select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
            Gallery.deleted_at.is_not(None),
        )
    )).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")
    _check_write_access(auth, g)
    g.deleted_at = None
    await db.commit()
    return {"status": "ok"}


@router.post("/galleries/{source}/{source_id}/permanent-delete")
async def permanent_delete_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a gallery (from trash). Irreversible."""
    g = (await db.execute(
        select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
            Gallery.deleted_at.is_not(None),
        )
    )).scalar_one_or_none()
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

    galleries = (await db.execute(
        select(Gallery).where(trash_cond)
    )).scalars().all()

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
    is_fav, my_rating = await _user_gallery_state(db, auth["user_id"], g.id)
    return _g(g, cover_thumb=cover_thumb, is_favorited=is_fav, my_rating=my_rating)


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
    stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id)
        .order_by(page_order)
        .options(selectinload(Image.blob))
    )

    # When limit is provided, return paginated response
    if limit is not None:
        p = page or 1
        total_stmt = select(func.count()).select_from(
            select(Image.id).where(Image.gallery_id == gallery_id).subquery()
        )
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = stmt.offset((p - 1) * limit).limit(limit)
        images = (await db.execute(stmt)).scalars().all()

        return {
            "gallery_id": gallery_id,
            "images": [_i(img) for img in images],
            "total": total,
            "page": p,
            "has_next": (p * limit) < total,
        }

    # Default: return all images (backward compatible for Reader)
    images = (await db.execute(stmt)).scalars().all()
    return {"gallery_id": gallery_id, "images": [_i(img) for img in images]}


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
        await db.execute(
            select(GalleryTag)
            .where(GalleryTag.gallery_id == gallery_id)
            .options(selectinload(GalleryTag.tag))
            .order_by(GalleryTag.confidence.desc())
        )
    ).scalars().all()

    tags = []
    for gt in rows:
        tag = gt.tag
        tags.append({
            "namespace": tag.namespace,
            "name": tag.name,
            "confidence": gt.confidence,
            "source": gt.source,
        })
    return {"gallery_id": gallery_id, "tags": tags}


# ── Gallery update ───────────────────────────────────────────────────


class GalleryPatch(BaseModel):
    favorited: bool | None = None
    rating: int | None = None
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
            stmt = pg_insert(UserFavorite).values(
                user_id=auth["user_id"], gallery_id=gallery_id,
            ).on_conflict_do_nothing()
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
            stmt = pg_insert(UserRating).values(
                user_id=auth["user_id"], gallery_id=gallery_id, rating=patch.rating,
            ).on_conflict_do_update(
                index_elements=["user_id", "gallery_id"],
                set_={"rating": patch.rating, "rated_at": func.now()},
            )
            await db.execute(stmt)
    if patch.title is not None:
        g.title = patch.title
    if patch.title_jpn is not None:
        g.title_jpn = patch.title_jpn
    if patch.category is not None:
        g.category = patch.category
    await db.commit()
    # Fetch updated per-user state to return accurate response
    is_fav, my_rating = await _user_gallery_state(db, auth["user_id"], gallery_id)
    return _g(g, is_favorited=is_fav, my_rating=my_rating)


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

    # Prevent deletion while download is active
    if g.download_status == "downloading":
        raise HTTPException(status_code=409, detail="Cannot delete gallery while downloading. Cancel the download first.")
    from db.models import DownloadJob
    active_job = (await db.execute(
        select(DownloadJob.id).where(
            DownloadJob.gallery_id == g.id,
            DownloadJob.status.in_(["queued", "running"]),
        ).limit(1)
    )).scalar_one_or_none()
    if active_job:
        raise HTTPException(status_code=409, detail="Cannot delete gallery with active download job. Cancel the download first.")

    g.deleted_at = datetime.now(UTC)
    await db.commit()
    await _invalidate_sources_cache()
    return {"status": "ok", "deleted_files": 0}


class DeleteImageBody(BaseModel):
    page_num: int


@router.post("/galleries/{source}/{source_id}/delete-image")
async def delete_gallery_image(
    source: str,
    source_id: str,
    body: DeleteImageBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single image from a gallery by page number.

    Removes the library symlink, decrements the blob ref count, deletes the
    Image record, re-numbers remaining pages sequentially, and cleans up
    thumbnail directories for any now-unreferenced blobs.
    """
    import asyncio
    import shutil

    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = gallery.id
    _check_write_access(auth, gallery)

    img_stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id, Image.page_num == body.page_num)
        .options(selectinload(Image.blob))
    )
    img = (await db.execute(img_stmt)).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")

    blob_sha256 = img.blob_sha256
    filename = img.filename

    # Record blob as excluded so re-imports skip it
    from db.models import ExcludedBlob
    excl_stmt = pg_insert(ExcludedBlob).values(
        gallery_id=gallery_id, blob_sha256=blob_sha256,
    ).on_conflict_do_nothing()
    await db.execute(excl_stmt)

    # Remove the symlink from the library directory (use gallery ORM attributes)
    symlink_path = library_dir(gallery.source, gallery.source_id) / filename
    await asyncio.to_thread(symlink_path.unlink, True)

    # Decrement blob ref count and delete image record
    await decrement_ref_count(blob_sha256, db)
    await db.delete(img)
    gallery.pages = max(0, (gallery.pages or 1) - 1)

    # Re-number remaining images sequentially starting at 1.
    # Two-pass approach to avoid unique constraint violations during renumber:
    # 1) Set all page_nums to negative temporaries, 2) Set to final positive values.
    remaining_stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id)
        .order_by(Image.page_num)
    )
    remaining = (await db.execute(remaining_stmt)).scalars().all()
    for i, remaining_img in enumerate(remaining):
        remaining_img.page_num = -(i + 1)
    await db.flush()
    for new_num, remaining_img in enumerate(remaining, start=1):
        remaining_img.page_num = new_num

    await db.commit()

    # Check if the blob is now unreferenced; if so, clean up its thumbnail directory
    zero_ref_result = await db.execute(
        select(Blob.sha256).where(Blob.sha256 == blob_sha256, Blob.ref_count <= 0)
    )
    zero_ref_sha256 = zero_ref_result.scalar_one_or_none()

    if zero_ref_sha256:
        td = thumb_dir(zero_ref_sha256)

        def _remove_thumbs() -> None:
            if td.exists():
                try:
                    shutil.rmtree(str(td), ignore_errors=True)
                except OSError as exc:
                    logger.warning("[delete_gallery_image] failed to remove thumb dir %s: %s", td, exc)

        await asyncio.to_thread(_remove_thumbs)

    return {"status": "ok", "remaining_pages": gallery.pages}


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
                        flipped ^= (1 << b)
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
        await db.execute(
            select(Image).where(Image.id == image_id).options(selectinload(Image.blob))
        )
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
                   bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int AS distance
            FROM images i
            JOIN blobs b ON i.blob_sha256 = b.sha256
            WHERE b.phash_int IS NOT NULL
              AND i.id != :image_id
              AND bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int <= :threshold
            ORDER BY distance ASC
            LIMIT :limit
        """)
        results = (await db.execute(stmt, {
            "phash_int": phash_int_val,
            "image_id": image_id,
            "threshold": threshold,
            "limit": limit,
        })).all()
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
                       bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int <= :threshold
                ORDER BY distance ASC
                LIMIT :limit
            """)
            results = (await db.execute(stmt, {
                "phash_int": phash_int_val,
                "image_id": image_id,
                "threshold": threshold,
                "limit": limit,
            })).all()
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
                       bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND ({where_prefilter})
                  AND bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int <= :threshold
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
        select(ExcludedBlob)
        .where(ExcludedBlob.gallery_id == gallery_id)
        .order_by(ExcludedBlob.excluded_at.desc())
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

    if source != "ehentai":
        return {"status": "skipped", "reason": "unsupported_source"}

    # Parse gid/token from source_url
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
            # Gallery was expunged — set timestamp so we don't re-check
            g.metadata_updated_at = func.now()
            await db.commit()
            await db.refresh(g)
            return {"status": "expunged"}
        # Other errors (auth, 509, etc.) — don't set timestamp, retry next visit
        return {"status": "error", "reason": str(exc)}
    except Exception:
        return {"status": "error", "reason": "fetch_failed"}

    # Snapshot before update
    old = {
        "title": g.title,
        "title_jpn": g.title_jpn,
        "category": g.category,
        "uploader": g.uploader,
        "pages": g.pages,
        "rating": g.rating,
        "tags_array": list(g.tags_array or []),
    }

    # Update source-level fields only (use `is not None` to allow 0/"" from source)
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

    # Convert EH tags (format: "namespace:tag") to tags_array
    if meta.get("tags"):
        g.tags_array = meta["tags"]

    # Build changed fields list
    changed_fields = [
        f for f in ("title", "title_jpn", "category", "uploader", "pages", "rating")
        if getattr(g, f) != old[f]
    ]
    if list(g.tags_array or []) != old["tags_array"]:
        changed_fields.append("tags")

    # Detect page count change
    pages_diff = None
    if "pages" in changed_fields:
        pages_diff = {"old": old["pages"], "new": g.pages}

    g.metadata_updated_at = func.now()
    await db.commit()
    await db.refresh(g)

    if not changed_fields:
        return {"status": "unchanged"}

    # Build response with updated gallery
    cover_thumb = await _single_cover_thumb(db, g.id, g.source or "")
    is_fav, my_rating = await _user_gallery_state(db, auth["user_id"], g.id)
    return {
        "status": "updated",
        "gallery": _g(g, cover_thumb, is_fav, my_rating),
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
    return cas_thumb_url(blob.sha256)


async def _get_or_404_by_source(db: AsyncSession, source: str, source_id: str, auth: dict | None = None) -> Gallery:
    """Fetch a gallery by (source, source_id) with optional access filter. Raises 404 if not found."""
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


def _g(g: Gallery, cover_thumb: str | None = None, is_favorited: bool = False, my_rating: int | None = None) -> dict:
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
        "uploader": g.uploader,
        "artist_id": g.artist_id,
        "download_status": g.download_status,
        "import_mode": g.import_mode,
        "tags_array": g.tags_array or [],
        "cover_thumb": cover_thumb,
        "source_url": g.source_url,
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
    }
