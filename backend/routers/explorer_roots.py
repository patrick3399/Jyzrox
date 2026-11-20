"""Explorer roots endpoint."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.redis_client import get_redis
from db.models import (
    Blob,
    BlobRelationship,
    Collection,
    CollectionGallery,
    Gallery,
    GalleryCategory,
    Image,
    LibraryPath,
    SavedSearch,
)
from services.explorer_filesystem import (
    read_folder_stats,
)
from services.explorer_requests import (
    enqueue_folder_stats as _enqueue_folder_stats,
)

router = APIRouter()
_member = require_role("member")


@router.get("/roots")
async def explorer_roots(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return virtual roots plus member-only configured physical roots."""
    accessible = gallery_access_filter(auth)
    counts = {
        row.source: row.count
        for row in (
            await db.execute(
                select(Gallery.source, func.count(Gallery.id).label("count")).where(accessible).group_by(Gallery.source)
            )
        ).all()
    }
    logical_rows = (
        await db.execute(
            select(Gallery.source, func.coalesce(func.sum(Blob.file_size), 0).label("size"))
            .select_from(Gallery)
            .join(Image, Image.gallery_id == Gallery.id)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(accessible)
            .group_by(Gallery.source)
        )
    ).all()
    logical = {row.source: int(row.size) for row in logical_rows}
    unique_rows = (
        select(Gallery.source.label("source"), Image.blob_sha256.label("sha"), Blob.file_size.label("size"))
        .select_from(Gallery)
        .join(Image, Image.gallery_id == Gallery.id)
        .join(Blob, Blob.sha256 == Image.blob_sha256)
        .where(accessible)
        .distinct()
        .subquery()
    )
    unique_sizes = {
        row.source: int(row.size)
        for row in (
            await db.execute(
                select(unique_rows.c.source, func.coalesce(func.sum(unique_rows.c.size), 0).label("size")).group_by(
                    unique_rows.c.source
                )
            )
        ).all()
    }
    sources = [
        {
            "id": source,
            "label": source,
            "gallery_count": count,
            "logical_bytes": logical.get(source, 0),
            "unique_cas_bytes": unique_sizes.get(source, 0),
        }
        for source, count in sorted(counts.items())
    ]

    owner_filter = True if auth["role"] == "admin" else Collection.user_id == auth["user_id"]
    collection_count = (await db.execute(select(func.count()).select_from(Collection).where(owner_filter))).scalar_one()
    collection_rows = (
        await db.execute(
            select(Collection.id, Collection.name, func.count(CollectionGallery.gallery_id).label("count"))
            .outerjoin(CollectionGallery, CollectionGallery.collection_id == Collection.id)
            .where(owner_filter)
            .group_by(Collection.id, Collection.name)
            .order_by(Collection.name)
            .limit(500)
        )
    ).all()
    saved_search_count = (
        await db.execute(select(func.count()).select_from(SavedSearch).where(SavedSearch.user_id == auth["user_id"]))
    ).scalar_one()
    saved_search_rows = (
        await db.execute(
            select(SavedSearch.id, SavedSearch.name, SavedSearch.query)
            .where(SavedSearch.user_id == auth["user_id"])
            .order_by(SavedSearch.name)
            .limit(200)
        )
    ).all()
    artist_count = (
        await db.execute(
            select(func.count(distinct(Gallery.artist_id))).where(accessible, Gallery.artist_id.is_not(None))
        )
    ).scalar_one()
    artist_rows = (
        await db.execute(
            select(Gallery.artist_id, func.count(Gallery.id).label("count"))
            .where(accessible, Gallery.artist_id.is_not(None))
            .group_by(Gallery.artist_id)
            .order_by(desc(func.count(Gallery.id)), Gallery.artist_id)
            .limit(500)
        )
    ).all()
    # ``gallery_access_filter`` already excludes trashed galleries.
    visible = [accessible]
    uncategorized_count = (
        await db.execute(
            select(func.count())
            .select_from(Gallery)
            .where(*visible, or_(Gallery.category.is_(None), Gallery.category == ""))
        )
    ).scalar_one()
    category_counts = {
        row.category: int(row.count)
        for row in (
            await db.execute(
                select(Gallery.category, func.count(Gallery.id).label("count"))
                .where(*visible, Gallery.category.is_not(None), Gallery.category != "")
                .group_by(Gallery.category)
            )
        ).all()
    }
    registry_names = (
        (await db.execute(select(GalleryCategory.name).order_by(GalleryCategory.sort_order, GalleryCategory.id)))
        .scalars()
        .all()
    )
    category_items = [
        {"id": name, "label": name, "gallery_count": category_counts.get(name, 0), "registered": True}
        for name in registry_names
    ]
    registered = set(registry_names)
    category_items.extend(
        {"id": name, "label": name, "gallery_count": count, "registered": False}
        for name, count in sorted(category_counts.items())
        if name not in registered
    )
    missing_metadata_count = (
        await db.execute(
            select(func.count())
            .select_from(Gallery)
            .where(accessible, or_(Gallery.title.is_(None), Gallery.pages.is_(None)))
        )
    ).scalar_one()
    empty_count = (
        await db.execute(
            select(func.count())
            .select_from(Gallery)
            .where(accessible, ~exists(select(Image.id).where(Image.gallery_id == Gallery.id)))
        )
    ).scalar_one()
    hidden_images_count = (
        await db.execute(
            select(func.count())
            .select_from(Gallery)
            .where(
                accessible,
                exists(select(Image.id).where(Image.gallery_id == Gallery.id, Image.visibility == "user_hidden")),
            )
        )
    ).scalar_one()
    hidden_bytes = (
        await db.execute(
            select(func.coalesce(func.sum(Blob.file_size), 0))
            .select_from(Gallery)
            .join(Image, Image.gallery_id == Gallery.id)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(accessible, Image.visibility == "user_hidden")
        )
    ).scalar_one()
    duplicate_count = (
        await db.execute(
            select(func.count())
            .select_from(BlobRelationship)
            .where(BlobRelationship.relationship.in_(("needs_t2", "potential")))
        )
    ).scalar_one()

    physical: list[dict[str, Any]] = []
    if auth["role"] in {"member", "admin"}:
        redis = get_redis()
        libraries = (
            (await db.execute(select(LibraryPath).where(LibraryPath.enabled.is_(True)).order_by(LibraryPath.id)))
            .scalars()
            .all()
        )
        for library in libraries:
            stats = await read_folder_stats(redis, library.id, "")
            if stats is None:
                await _enqueue_folder_stats(library.id, "")
            physical.append(
                {
                    "id": library.id,
                    "label": library.label or Path(library.path).name or f"Library {library.id}",
                    "import_mode": library.import_mode,
                    "pattern": library.pattern,
                    "size_status": "ready" if stats else "pending",
                    "physical_bytes": stats.get("physical_bytes") if stats else None,
                    "size_updated_at": stats.get("updated_at") if stats else None,
                }
            )

    return {
        "virtual": {
            "sources": sources,
            "collections": {
                "count": collection_count,
                "items": [{"id": row.id, "name": row.name, "gallery_count": row.count} for row in collection_rows],
            },
            "artists": {
                "count": artist_count,
                "items": [
                    {"id": row.artist_id, "name": row.artist_id, "gallery_count": row.count} for row in artist_rows
                ],
            },
            "categories": {"uncategorized": uncategorized_count, "items": category_items},
            "saved_searches": {
                "count": saved_search_count,
                "items": [{"id": row.id, "name": row.name, "query": row.query} for row in saved_search_rows],
            },
            "smart_views": {
                "missing_metadata": missing_metadata_count,
                "empty_galleries": empty_count,
                "duplicate_pairs": duplicate_count,
                "hidden_images": hidden_images_count,
                "hidden_bytes": int(hidden_bytes or 0),
                "trash": True,
            },
        },
        "physical": physical,
    }
