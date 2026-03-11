"""Unified search endpoint for galleries."""

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, asc, cast, desc, func, or_, select

from core.auth import require_auth
from core.database import async_session
from db.models import Gallery, SavedSearch

router = APIRouter(tags=["search"])


# ── Cursor helpers ────────────────────────────────────────────────────


def _encode_cursor(row: Gallery, sort: str) -> str:
    sort_val = {
        "added_at": row.added_at.isoformat() if row.added_at else "",
        "rating": row.rating,
        "pages": row.pages if row.pages is not None else 0,
        "posted_at": row.posted_at.isoformat() if row.posted_at else "",
        "title": row.title or "",
    }[sort]
    payload = {"id": row.id, "v": str(sort_val), "s": sort}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + "=="))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/")
async def search_galleries(
    q: str = Query(
        "",
        description='Search query: tags (character:rem), exclude (-general:sketch), title (title:"re zero"), source (source:ehentai), rating (rating:>=4), favorited (favorited:true), sort (sort:rating)',
    ),
    sort: str = "added_at",
    page: int = 1,
    limit: int = 24,
    cursor: str | None = Query(default=None),
    _: dict = Depends(require_auth),
):
    """
    Unified search with full query syntax:
      character:rem general:blue_hair   → include tags (AND)
      -general:sketch                   → exclude tag
      title:"re zero"                   → fuzzy title search (pg_trgm ILIKE)
      source:ehentai                    → source filter
      rating:>=4                        → minimum rating
      favorited:true                    → favorited only
      sort:rating                       → override sort order

    Supports cursor-based pagination (cursor=) for deep pages without COUNT(*)/OFFSET cost.
    When cursor is absent, falls back to OFFSET-based pagination (page-based, max page 500).
    """
    tokens = q.split()[:20]
    include_tags: list[str] = []
    exclude_tags: list[str] = []
    text_queries: list[str] = []
    source_filter: str | None = None
    rating_filter: int | None = None
    favorited_filter: bool | None = None

    for t in tokens:
        if t.startswith("title:"):
            text_queries.append(t[6:].strip('"'))
        elif t.startswith("source:"):
            source_filter = t[7:]
        elif t.startswith("rating:"):
            val = t[7:].lstrip(">=<")
            try:
                rating_filter = int(val)
            except ValueError:
                pass
        elif t.startswith("favorited:"):
            favorited_filter = t[10:].lower() == "true"
        elif t.startswith("sort:"):
            sort = t[5:]
        elif t.startswith("-"):
            exclude_tags.append(t[1:])
        else:
            include_tags.append(t)

    # Build filters
    filters = []

    if include_tags:
        filters.append(Gallery.tags_array.contains(cast(include_tags, ARRAY(Text))))

    if exclude_tags:
        filters.append(~Gallery.tags_array.overlap(cast(exclude_tags, ARRAY(Text))))

    if text_queries:
        tq = f"%{text_queries[0]}%"
        filters.append((Gallery.title.ilike(tq)) | (Gallery.title_jpn.ilike(tq)))

    if source_filter:
        filters.append(Gallery.source == source_filter)

    if rating_filter is not None:
        filters.append(Gallery.rating >= rating_filter)

    if favorited_filter is not None:
        filters.append(Gallery.favorited == favorited_filter)

    # Sort — DESC for numeric/date columns, ASC for title
    _desc_sorts = {"added_at", "rating", "pages", "posted_at"}
    sort_map = {
        "added_at": desc(Gallery.added_at),
        "rating": desc(Gallery.rating),
        "pages": desc(Gallery.pages),
        "posted_at": desc(Gallery.posted_at),
        "title": asc(Gallery.title),
    }
    order = sort_map.get(sort, desc(Gallery.added_at))
    effective_sort = sort if sort in sort_map else "added_at"

    def _row_to_item(r: Gallery) -> dict:
        return {
            "id": r.id,
            "title": r.title,
            "title_jpn": r.title_jpn,
            "source": r.source,
            "source_id": r.source_id,
            "category": r.category,
            "language": r.language,
            "pages": r.pages,
            "rating": r.rating,
            "favorited": r.favorited,
            "uploader": r.uploader,
            "download_status": r.download_status,
            "added_at": r.added_at.isoformat() if r.added_at else None,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
            "tags": r.tags_array or [],
        }

    async with async_session() as session:
        if cursor is not None:
            # Keyset pagination — no COUNT(*), no OFFSET
            c = _decode_cursor(cursor)
            if c.get("s") != effective_sort:
                raise HTTPException(status_code=400, detail="Cursor sort key does not match current sort parameter")

            cursor_id = c["id"]
            cursor_val = c["v"]

            base_stmt = select(Gallery).where(*filters)

            if effective_sort == "added_at":
                from datetime import datetime as _dt

                try:
                    parsed = _dt.fromisoformat(cursor_val)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor value")
                base_stmt = base_stmt.where(
                    or_(
                        Gallery.added_at < parsed,
                        and_(Gallery.added_at == parsed, Gallery.id < cursor_id),
                    )
                )
            elif effective_sort == "posted_at":
                from datetime import datetime as _dt

                try:
                    parsed = _dt.fromisoformat(cursor_val)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor value")
                base_stmt = base_stmt.where(
                    or_(
                        Gallery.posted_at < parsed,
                        and_(Gallery.posted_at == parsed, Gallery.id < cursor_id),
                    )
                )
            elif effective_sort == "rating":
                try:
                    cv = int(cursor_val)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor value")
                base_stmt = base_stmt.where(
                    or_(
                        Gallery.rating < cv,
                        and_(Gallery.rating == cv, Gallery.id < cursor_id),
                    )
                )
            elif effective_sort == "pages":
                try:
                    cv = int(cursor_val)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid cursor value")
                base_stmt = base_stmt.where(
                    or_(
                        Gallery.pages < cv,
                        and_(Gallery.pages == cv, Gallery.id < cursor_id),
                    )
                )
            else:
                # title: ASC sort — next page means title > cursor_val, tie-break id ASC
                base_stmt = base_stmt.where(
                    or_(
                        Gallery.title > cursor_val,
                        and_(Gallery.title == cursor_val, Gallery.id > cursor_id),
                    )
                )

            # For DESC sorts tie-break on id DESC; ASC (title) tie-break on id ASC
            if effective_sort == "title":
                data_query = base_stmt.order_by(asc(Gallery.title), asc(Gallery.id)).limit(limit + 1)
            else:
                data_query = base_stmt.order_by(order, desc(Gallery.id)).limit(limit + 1)

            rows = (await session.execute(data_query)).scalars().all()
            has_next = len(rows) > limit
            if has_next:
                rows = rows[:limit]

            next_cursor = _encode_cursor(rows[-1], effective_sort) if has_next and rows else None
            return {
                "query": q,
                "items": [_row_to_item(r) for r in rows],
                "next_cursor": next_cursor,
                "has_next": has_next,
            }

        else:
            # Legacy page-based pagination
            if page > 500:
                raise HTTPException(
                    status_code=400, detail="Page depth exceeds limit. Use cursor= for deep pagination."
                )

            offset = (page - 1) * limit

            count_query = select(func.count()).select_from(Gallery).where(*filters)
            total = (await session.execute(count_query)).scalar()

            data_query = select(Gallery).where(*filters).order_by(order).limit(limit).offset(offset)
            rows = (await session.execute(data_query)).scalars().all()

    return {
        "total": total,
        "page": page,
        "query": q,
        "items": [_row_to_item(r) for r in rows],
    }


# ── Saved Searches ────────────────────────────────────────────────────


class SavedSearchCreate(BaseModel):
    name: str
    query: str = ""
    params: dict = {}


class SavedSearchRename(BaseModel):
    name: str


@router.get("/saved")
async def list_saved_searches(
    auth: dict = Depends(require_auth),
):
    """List saved searches for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        rows = (
            await session.execute(
                select(SavedSearch)
                .where(SavedSearch.user_id == user_id)
                .order_by(desc(SavedSearch.created_at))
                .limit(200)
            )
        ).scalars().all()
    return {"searches": [_ss(r) for r in rows]}


@router.post("/saved", status_code=201)
async def create_saved_search(
    body: SavedSearchCreate,
    auth: dict = Depends(require_auth),
):
    """Save a search for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        row = SavedSearch(
            user_id=user_id,
            name=body.name,
            query=body.query,
            params=body.params,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _ss(row)


@router.delete("/saved/{saved_id}")
async def delete_saved_search(
    saved_id: int,
    auth: dict = Depends(require_auth),
):
    """Delete a saved search."""
    user_id = auth["user_id"]
    async with async_session() as session:
        row = (
            await session.execute(
                select(SavedSearch).where(
                    SavedSearch.id == saved_id,
                    SavedSearch.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Saved search not found")
        await session.delete(row)
        await session.commit()
    return {"status": "ok"}


@router.patch("/saved/{saved_id}")
async def rename_saved_search(
    saved_id: int,
    body: SavedSearchRename,
    auth: dict = Depends(require_auth),
):
    """Rename a saved search."""
    user_id = auth["user_id"]
    async with async_session() as session:
        row = (
            await session.execute(
                select(SavedSearch).where(
                    SavedSearch.id == saved_id,
                    SavedSearch.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Saved search not found")
        row.name = body.name
        await session.commit()
        await session.refresh(row)
    return _ss(row)


def _ss(r: SavedSearch) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "query": r.query,
        "params": r.params or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
