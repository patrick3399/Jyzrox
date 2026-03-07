"""Unified search endpoint for galleries."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from core.database import async_session
from core.auth import require_auth
from sqlalchemy import text

router = APIRouter(tags=["search"])


@router.get("/")
async def search_galleries(
    q: str = Query("", description="Search query: tags (character:rem), exclude (-general:sketch), title (title:\"re zero\"), source (source:ehentai), rating (rating:>=4), favorited (favorited:true), sort (sort:rating)"),
    sort: str = "added_at",
    page: int = 1,
    limit: int = 24,
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
    """
    tokens = q.split()
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

    offset = (page - 1) * limit
    conditions: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

    if include_tags:
        conditions.append("tags_array @> :inc_tags")
        params["inc_tags"] = include_tags

    if exclude_tags:
        conditions.append("NOT (tags_array && :exc_tags)")
        params["exc_tags"] = exclude_tags

    if text_queries:
        conditions.append("(title ILIKE :tq OR title_jpn ILIKE :tq)")
        params["tq"] = f"%{text_queries[0]}%"

    if source_filter:
        conditions.append("source = :source")
        params["source"] = source_filter

    if rating_filter is not None:
        conditions.append("rating >= :min_rating")
        params["min_rating"] = rating_filter

    if favorited_filter is not None:
        conditions.append("favorited = :fav")
        params["fav"] = favorited_filter

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Sort
    sort_map = {
        "added_at": "added_at DESC",
        "rating": "rating DESC",
        "pages": "pages DESC",
        "posted_at": "posted_at DESC",
        "title": "title ASC",
    }
    order = sort_map.get(sort, "added_at DESC")

    # Count
    async with async_session() as session:
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM galleries {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar()

        result = await session.execute(
            text(f"""
                SELECT id, title, title_jpn, source, source_id, category, language,
                       pages, rating, favorited, uploader, download_status,
                       added_at, posted_at, tags_array
                FROM galleries {where}
                ORDER BY {order}
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

    return {
        "total": total,
        "page": page,
        "query": q,
        "items": [
            {
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
            for r in rows
        ],
    }
