"""Library split from routers/library.py (library_galleries_list)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from core.gallery_helpers import (
    build_cover_map,
    get_blocked_tag_strings,
    get_favorite_set,
    get_rating_map,
    get_reading_list_set,
)
from core.utils import escape_like
from db.models import (
    Gallery,
    UserFavorite,
    UserRating,
    UserReadingList,
)
from services.library_helpers import decode_cursor as _decode_cursor
from services.library_helpers import encode_cursor as _encode_cursor
from services.library_serializers import serialize_gallery as _g

# Backward-compat aliases — functions now live in core.gallery_helpers
_get_favorite_set = get_favorite_set
_get_reading_list_set = get_reading_list_set
_get_rating_map = get_rating_map
_get_blocked_tag_strings = get_blocked_tag_strings
_build_cover_map = build_cover_map
router = APIRouter()


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
    sort: Literal["added_at", "content_updated_at", "rating", "pages"] = Query(default="added_at"),
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
        pattern = f"%{escape_like(q)}%"
        stmt = stmt.where(
            or_(
                Gallery.title.ilike(pattern, escape="\\"),
                Gallery.title_jpn.ilike(pattern, escape="\\"),
            )
        )
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

    sort_col = {
        "added_at": Gallery.added_at,
        "content_updated_at": Gallery.content_updated_at,
        "rating": Gallery.rating,
        "pages": Gallery.pages,
    }[sort]

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
        elif sort == "content_updated_at":
            from datetime import datetime as _dt

            try:
                parsed = _dt.fromisoformat(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.content_updated_at < parsed,
                    and_(Gallery.content_updated_at == parsed, Gallery.id < cursor_id),
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
