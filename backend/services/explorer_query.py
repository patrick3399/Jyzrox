"""Reusable Gallery query construction for Workbench pages and selections."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import asc, desc, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import (
    BlobRelationship,
    CollectionGallery,
    Gallery,
    Image,
    SavedSearch,
    UserFavorite,
    UserReadingList,
)


@dataclass(slots=True)
class ExplorerQuerySpec:
    node_kind: str = "all"
    node_id: str | None = None
    query: str = ""
    sort: str = "added_at"
    direction: str = "desc"


def _tokens(query: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    quoted = False
    for character in query.strip():
        if character == '"':
            quoted = not quoted
        elif character.isspace() and not quoted:
            if current:
                result.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        result.append("".join(current))
    return result[:20]


def _value(token: str) -> str:
    value = token.split(":", 1)[1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


async def normalize_explorer_query(
    db: AsyncSession,
    spec: ExplorerQuerySpec,
    auth: dict,
) -> ExplorerQuerySpec:
    """Expand an owned saved-search node into its stored query and sort."""
    if spec.node_kind != "saved_search":
        return spec
    try:
        saved_id = int(spec.node_id or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid saved search id")
    saved = (
        await db.execute(select(SavedSearch).where(SavedSearch.id == saved_id, SavedSearch.user_id == auth["user_id"]))
    ).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    params: dict[str, Any] = saved.params or {}
    return ExplorerQuerySpec(
        node_kind="all",
        query=saved.query or spec.query,
        sort=str(params.get("sort") or spec.sort),
        direction=str(params.get("direction") or spec.direction),
    )


def build_explorer_gallery_query(spec: ExplorerQuerySpec, auth: dict):
    """Build an access-filtered Gallery select from a Workbench predicate spec."""
    if spec.node_kind == "trash":
        filters = [Gallery.deleted_at.is_not(None)]
        if auth["role"] != "admin":
            filters.append(or_(Gallery.created_by_user_id == auth["user_id"], Gallery.created_by_user_id.is_(None)))
    else:
        filters = [gallery_access_filter(auth)]

    if spec.node_kind == "source" and spec.node_id:
        filters.append(Gallery.source == spec.node_id)
    elif spec.node_kind == "collection" and spec.node_id:
        filters.append(
            Gallery.id.in_(
                select(CollectionGallery.gallery_id).where(CollectionGallery.collection_id == int(spec.node_id))
            )
        )
    elif spec.node_kind == "artist" and spec.node_id:
        filters.append(Gallery.artist_id == spec.node_id)
    elif spec.node_kind == "smart" and spec.node_id:
        if spec.node_id == "missing_metadata":
            filters.append(or_(Gallery.title.is_(None), Gallery.pages.is_(None)))
        elif spec.node_id == "empty_galleries":
            filters.append(~exists(select(Image.id).where(Image.gallery_id == Gallery.id)))
        elif spec.node_id == "duplicates":
            related_hashes = select(BlobRelationship.sha_a).union(select(BlobRelationship.sha_b))
            filters.append(Gallery.id.in_(select(Image.gallery_id).where(Image.blob_sha256.in_(related_hashes))))
        else:
            raise HTTPException(status_code=400, detail="Unknown smart view")
    elif spec.node_kind not in {"all", "trash", "source", "collection", "artist"}:
        raise HTTPException(status_code=400, detail="Unknown Explorer node")

    for token in _tokens(spec.query):
        if token.startswith("title:"):
            pattern = f"%{_value(token)}%"
            filters.append(or_(Gallery.title.ilike(pattern), Gallery.title_jpn.ilike(pattern)))
        elif token.startswith("source:"):
            filters.append(Gallery.source == _value(token))
        elif token.startswith("artist_id:"):
            filters.append(Gallery.artist_id == _value(token))
        elif token.startswith("category:"):
            value = _value(token)
            filters.append(
                or_(Gallery.category.is_(None), Gallery.category == "")
                if value == "__uncategorized__"
                else Gallery.category == value
            )
        elif token.startswith("language:"):
            filters.append(Gallery.language == _value(token))
        elif token.startswith("rating:"):
            try:
                filters.append(Gallery.rating >= int(_value(token).lstrip("><=")))
            except ValueError:
                continue
        elif token.startswith("favorited:") and _value(token).lower() == "true":
            filters.append(
                Gallery.id.in_(select(UserFavorite.gallery_id).where(UserFavorite.user_id == auth["user_id"]))
            )
        elif token.startswith("rl:") and _value(token).lower() == "true":
            filters.append(
                Gallery.id.in_(select(UserReadingList.gallery_id).where(UserReadingList.user_id == auth["user_id"]))
            )
        elif token.startswith("collection:"):
            try:
                collection_id = int(_value(token))
            except ValueError:
                continue
            filters.append(
                Gallery.id.in_(
                    select(CollectionGallery.gallery_id).where(CollectionGallery.collection_id == collection_id)
                )
            )
        elif token.startswith("-") and ":" in token:
            filters.append(~Gallery.tags_array.overlap([token[1:]]))
        elif ":" in token:
            filters.append(Gallery.tags_array.contains([token]))
        else:
            pattern = f"%{token}%"
            filters.append(
                or_(
                    Gallery.title.ilike(pattern),
                    Gallery.title_jpn.ilike(pattern),
                    Gallery.uploader.ilike(pattern),
                    Gallery.artist_id.ilike(pattern),
                    Gallery.source_id.ilike(pattern),
                )
            )

    sort_columns = {
        "added_at": Gallery.added_at,
        "posted_at": Gallery.posted_at,
        "title": Gallery.title,
        "rating": Gallery.rating,
        "pages": Gallery.pages,
    }
    sort_column = sort_columns.get(spec.sort, Gallery.added_at)
    order = asc(sort_column) if spec.direction == "asc" else desc(sort_column)
    return select(Gallery).where(*filters).order_by(order, desc(Gallery.id))
