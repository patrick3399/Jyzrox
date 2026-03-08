"""Unified search endpoint for galleries."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from core.database import async_session
from core.auth import require_auth
from sqlalchemy import select, func, desc, asc, cast, ARRAY, Text
from db.models import Gallery

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

    # Build filters
    filters = []

    if include_tags:
        filters.append(Gallery.tags_array.contains(cast(include_tags, ARRAY(Text))))

    if exclude_tags:
        filters.append(~Gallery.tags_array.overlap(cast(exclude_tags, ARRAY(Text))))

    if text_queries:
        tq = f"%{text_queries[0]}%"
        filters.append(
            (Gallery.title.ilike(tq)) | (Gallery.title_jpn.ilike(tq))
        )

    if source_filter:
        filters.append(Gallery.source == source_filter)

    if rating_filter is not None:
        filters.append(Gallery.rating >= rating_filter)

    if favorited_filter is not None:
        filters.append(Gallery.favorited == favorited_filter)

    # Sort
    sort_map = {
        "added_at": desc(Gallery.added_at),
        "rating": desc(Gallery.rating),
        "pages": desc(Gallery.pages),
        "posted_at": desc(Gallery.posted_at),
        "title": asc(Gallery.title),
    }
    order = sort_map.get(sort, desc(Gallery.added_at))

    async with async_session() as session:
        count_query = select(func.count()).select_from(Gallery).where(*filters)
        total = (await session.execute(count_query)).scalar()

        data_query = (
            select(Gallery)
            .where(*filters)
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(data_query)).scalars().all()

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
