"""Unified search endpoint for galleries."""

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, asc, cast, desc, func, or_, select

from core.auth import gallery_access_filter, require_auth
from core.database import async_session
from db.models import BlockedTag, Gallery, SavedSearch, Tag, TagAlias, UserFavorite, UserRating

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
    auth: dict = Depends(require_auth),
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

    if text_queries:
        tq = f"%{text_queries[0]}%"
        filters.append((Gallery.title.ilike(tq)) | (Gallery.title_jpn.ilike(tq)))

    if source_filter:
        filters.append(Gallery.source == source_filter)

    if exclude_tags:
        filters.append(~Gallery.tags_array.overlap(cast(exclude_tags, ARRAY(Text))))

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
            "favorited": False,
            "uploader": r.uploader,
            "download_status": r.download_status,
            "added_at": r.added_at.isoformat() if r.added_at else None,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
            "tags": r.tags_array or [],
        }

    async with async_session() as session:
        # ── Blocked tags — query user's blocked tags ──
        blocked_rows = (
            await session.execute(
                select(BlockedTag.namespace, BlockedTag.name).where(
                    BlockedTag.user_id == auth["user_id"]
                )
            )
        ).all()
        if blocked_rows:
            blocked_strings = [f"{r.namespace}:{r.name}" for r in blocked_rows]
            filters.append(~Gallery.tags_array.overlap(cast(blocked_strings, ARRAY(Text))))

        # ── Alias expansion — batch resolve all include tags ──
        if include_tags:
            parsed_includes: list[tuple[str, str]] = []
            for tag_str in include_tags:
                if ":" in tag_str:
                    ns, name = tag_str.split(":", 1)
                else:
                    ns, name = "general", tag_str
                parsed_includes.append((ns, name))

            # Batch 1: Find which include tags are aliases
            alias_map: dict[tuple[str, str], int] = {}
            alias_rows = (
                await session.execute(
                    select(
                        TagAlias.alias_namespace,
                        TagAlias.alias_name,
                        TagAlias.canonical_id,
                    ).where(
                        or_(
                            *[
                                (TagAlias.alias_namespace == ns) & (TagAlias.alias_name == name)
                                for ns, name in parsed_includes
                            ]
                        )
                    )
                )
            ).all()
            for row in alias_rows:
                alias_map[(row.alias_namespace, row.alias_name)] = row.canonical_id

            # Batch 2: For non-alias tags, check if they are canonical tags
            non_alias_pairs = [
                (ns, name) for ns, name in parsed_includes
                if (ns, name) not in alias_map
            ]
            tag_id_map: dict[tuple[str, str], int] = {}
            if non_alias_pairs:
                tag_rows = (
                    await session.execute(
                        select(Tag.id, Tag.namespace, Tag.name).where(
                            or_(
                                *[
                                    (Tag.namespace == ns) & (Tag.name == name)
                                    for ns, name in non_alias_pairs
                                ]
                            )
                        )
                    )
                ).all()
                for row in tag_rows:
                    tag_id_map[(row.namespace, row.name)] = row.id

            # Collect all canonical_ids we need to expand
            all_canonical_ids: set[int] = set(alias_map.values())
            all_canonical_ids.update(tag_id_map.values())

            # Batch 3: Fetch canonical tag names + all aliases for all canonical_ids
            canonical_name_map: dict[int, str] = {}
            canonical_aliases_map: dict[int, list[str]] = {}
            if all_canonical_ids:
                canon_rows = (
                    await session.execute(
                        select(Tag.id, Tag.namespace, Tag.name).where(
                            Tag.id.in_(all_canonical_ids)
                        )
                    )
                ).all()
                for row in canon_rows:
                    canonical_name_map[row.id] = f"{row.namespace}:{row.name}"

                all_alias_rows = (
                    await session.execute(
                        select(
                            TagAlias.canonical_id,
                            TagAlias.alias_namespace,
                            TagAlias.alias_name,
                        ).where(TagAlias.canonical_id.in_(all_canonical_ids))
                    )
                ).all()
                for row in all_alias_rows:
                    canonical_aliases_map.setdefault(row.canonical_id, []).append(
                        f"{row.alias_namespace}:{row.alias_name}"
                    )

            # Build filter per include tag: AND across tags, OR across aliases
            for i, tag_str in enumerate(include_tags):
                ns, name = parsed_includes[i]
                canonical_id = alias_map.get((ns, name)) or tag_id_map.get((ns, name))
                if not canonical_id:
                    # No aliases found — exact match only
                    filters.append(Gallery.tags_array.contains(cast([tag_str], ARRAY(Text))))
                else:
                    variants = [tag_str]
                    canon_str = canonical_name_map.get(canonical_id)
                    if canon_str and canon_str not in variants:
                        variants.append(canon_str)
                    for alias_str in canonical_aliases_map.get(canonical_id, []):
                        if alias_str not in variants:
                            variants.append(alias_str)
                    if len(variants) == 1:
                        filters.append(Gallery.tags_array.contains(cast(variants, ARRAY(Text))))
                    else:
                        filters.append(Gallery.tags_array.overlap(cast(variants, ARRAY(Text))))

        if rating_filter is not None:
            filters.append(
                Gallery.id.in_(
                    select(UserRating.gallery_id).where(
                        UserRating.user_id == auth["user_id"],
                        UserRating.rating >= rating_filter,
                    )
                )
            )

        if favorited_filter is not None:
            if favorited_filter:
                filters.append(
                    Gallery.id.in_(
                        select(UserFavorite.gallery_id).where(UserFavorite.user_id == auth["user_id"])
                    )
                )
        if cursor is not None:
            # Keyset pagination — no COUNT(*), no OFFSET
            c = _decode_cursor(cursor)
            if c.get("s") != effective_sort:
                raise HTTPException(status_code=400, detail="Cursor sort key does not match current sort parameter")

            cursor_id = c["id"]
            cursor_val = c["v"]

            base_stmt = select(Gallery).where(*filters, gallery_access_filter(auth))

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

            count_query = select(func.count()).select_from(Gallery).where(*filters, gallery_access_filter(auth))
            total = (await session.execute(count_query)).scalar()

            data_query = select(Gallery).where(*filters, gallery_access_filter(auth)).order_by(order).limit(limit).offset(offset)
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
