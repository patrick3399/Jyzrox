"""Unified search endpoint for galleries."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from core.database import async_session
from core.auth import require_auth
from sqlalchemy import text

router = APIRouter(tags=["search"])

class SearchResult(BaseModel):
    id: int
    title: str
    source: str
    tags: List[str]

@router.get("/")
async def search_galleries(
    q: str = Query("", description="Search query supporting tags (e.g. character:rem) and text (e.g. title:\"re zero\")"),
    sort: str = "added_at",
    page: int = 1,
    limit: int = 24,
    _: dict = Depends(require_auth),
):
    # Parse query into tags array and text search
    # This is a simplified parser for phase 2.
    tokens = q.split()
    tags = []
    text_query = []
    for t in tokens:
        if t.startswith("title:"):
            text_query.append(t[6:].strip('"'))
        else:
            tags.append(t)

    offset = (page - 1) * limit

    base_query = "SELECT id, title, source, tags_array FROM galleries WHERE 1=1"
    params = {"limit": limit, "offset": offset}

    if tags:
        base_query += " AND tags_array @> :tags"
        params["tags"] = tags
    
    if text_query:
        # naive fuzzy search using pg_trgm for the first text query
        base_query += " AND (title ILIKE :tq OR title_jpn ILIKE :tq)"
        params["tq"] = f"%{text_query[0]}%"

    # Ordering
    if sort == "added_at":
        base_query += " ORDER BY added_at DESC"
    elif sort == "rating":
        base_query += " ORDER BY rating DESC"
    elif sort == "pages":
        base_query += " ORDER BY pages DESC"
    else:
        base_query += " ORDER BY added_at DESC"

    base_query += " LIMIT :limit OFFSET :offset"

    async with async_session() as session:
        result = await session.execute(text(base_query), params)
        rows = result.fetchall()

    return {
        "items": [
            {"id": r.id, "title": r.title, "source": r.source, "tags": r.tags_array}
            for r in rows
        ],
        "page": page,
        "query": q
    }
