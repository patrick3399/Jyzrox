"""Library Workbench APIs for navigation, bulk metadata, and merge."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from core.gallery_helpers import (
    build_cover_map,
    get_favorite_set,
    get_rating_map,
    get_reading_list_set,
)
from core.redis_client import get_redis
from db.models import (
    Blob,
    BlobRelationship,
    Collection,
    CollectionGallery,
    DownloadJob,
    Gallery,
    GalleryMetadataChange,
    GalleryMetadataFieldState,
    GalleryTag,
    Image,
    LibraryPath,
    SavedSearch,
    Tag,
    UserFavorite,
    UserRating,
    UserReadingList,
    WorkbenchOperation,
)
from services.explorer_filesystem import (
    MEDIA_EXTENSIONS,
    detect_media_type,
    folder_stats_job_id,
    folder_stats_key,
    read_folder_stats,
    relative_posix,
    resolve_library_relative,
)
from services.explorer_query import (
    ExplorerQuerySpec,
    build_explorer_gallery_query,
    normalize_explorer_query,
)
from services.workbench_metadata import (
    apply_manual_scalar_changes,
    load_accessible_galleries,
    load_writable_galleries,
)

router = APIRouter(tags=["explorer"])
_member = require_role("member")


class ScalarMutation(BaseModel):
    mode: Literal["keep", "set", "clear"] = "keep"
    value: Any | None = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.mode == "set" and self.value is None:
            raise ValueError("value is required when mode is set")
        return self


class BulkMetadataRequest(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    selection_token: str | None = None
    excluded_ids: list[int] = Field(default_factory=list, max_length=10_000)
    fields: dict[str, ScalarMutation] = Field(default_factory=dict, max_length=7)
    lock_fields: bool = True

    @model_validator(mode="after")
    def validate_selection(self):
        if bool(self.gallery_ids) == bool(self.selection_token):
            raise ValueError("Provide gallery_ids or selection_token, but not both")
        return self


class BulkDeleteRequest(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    selection_token: str | None = None
    excluded_ids: list[int] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_selection(self):
        if bool(self.gallery_ids) == bool(self.selection_token):
            raise ValueError("Provide gallery_ids or selection_token, but not both")
        return self


class BulkActionRequest(BulkDeleteRequest):
    action: Literal[
        "favorite",
        "unfavorite",
        "rate",
        "add_read_later",
        "remove_read_later",
        "add_collection",
        "remove_collection",
        "add_tags",
        "remove_tags",
    ]
    rating: int | None = Field(default=None, ge=0, le=5)
    collection_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=100)


class MergeRequest(BaseModel):
    gallery_ids: list[int] = Field(min_length=2, max_length=50)
    target_id: int
    scalar_sources: dict[str, int] = Field(default_factory=dict)


class ExplorerQueryRequest(BaseModel):
    node_kind: Literal["all", "source", "collection", "artist", "saved_search", "smart", "trash"] = "all"
    node_id: str | None = None
    query: str = Field(default="", max_length=1000)
    sort: Literal["added_at", "posted_at", "title", "rating", "pages"] = "added_at"
    direction: Literal["asc", "desc"] = "desc"
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=60, ge=1, le=200)


class CreateSelectionRequest(BaseModel):
    query: ExplorerQueryRequest


async def _resolve_bulk_selection(
    request: BulkMetadataRequest | BulkDeleteRequest | BulkActionRequest,
    auth: dict,
) -> list[int]:
    if request.gallery_ids:
        return list(dict.fromkeys(request.gallery_ids))
    redis = get_redis()
    raw = await redis.get(f"explorer:selection:{request.selection_token}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except TypeError, ValueError:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    if payload.get("user_id") != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    excluded = set(request.excluded_ids)
    return [int(gallery_id) for gallery_id in payload.get("gallery_ids", []) if int(gallery_id) not in excluded]


@router.post("/query")
async def query_explorer(
    request: ExplorerQueryRequest,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Query virtual Workbench nodes using predicate-style filters."""
    spec = await normalize_explorer_query(
        db,
        ExplorerQuerySpec(
            node_kind=request.node_kind,
            node_id=request.node_id,
            query=request.query,
            sort=request.sort,
            direction=request.direction,
        ),
        auth,
    )
    statement = build_explorer_gallery_query(spec, auth)
    total = (await db.execute(select(func.count()).select_from(statement.order_by(None).subquery()))).scalar_one()
    galleries = (await db.execute(statement.offset(request.offset).limit(request.limit))).scalars().all()
    gallery_ids = [gallery.id for gallery in galleries]
    cover_map = await build_cover_map(db, gallery_ids, {gallery.id: gallery.source for gallery in galleries})
    favorite_set = await get_favorite_set(db, auth["user_id"], gallery_ids)
    rating_map = await get_rating_map(db, auth["user_id"], gallery_ids)
    reading_set = await get_reading_list_set(db, auth["user_id"], gallery_ids)

    logical_sizes: dict[int, int] = {}
    unique_sizes: dict[int, int] = {}
    if gallery_ids:
        logical_sizes = {
            row.gallery_id: int(row.size)
            for row in (
                await db.execute(
                    select(Image.gallery_id, func.coalesce(func.sum(Blob.file_size), 0).label("size"))
                    .join(Blob, Blob.sha256 == Image.blob_sha256)
                    .where(Image.gallery_id.in_(gallery_ids))
                    .group_by(Image.gallery_id)
                )
            ).all()
        }
        unique_rows = (
            select(Image.gallery_id.label("gallery_id"), Image.blob_sha256, Blob.file_size.label("size"))
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.gallery_id.in_(gallery_ids))
            .distinct()
            .subquery()
        )
        unique_sizes = {
            row.gallery_id: int(row.size)
            for row in (
                await db.execute(
                    select(unique_rows.c.gallery_id, func.sum(unique_rows.c.size).label("size")).group_by(
                        unique_rows.c.gallery_id
                    )
                )
            ).all()
        }

    return {
        "total": total,
        "offset": request.offset,
        "limit": request.limit,
        "items": [
            {
                "id": gallery.id,
                "source": gallery.source,
                "source_id": gallery.source_id,
                "title": gallery.title,
                "title_jpn": gallery.title_jpn,
                "category": gallery.category,
                "language": gallery.language,
                "artist_id": gallery.artist_id,
                "uploader": gallery.uploader,
                "visibility": gallery.visibility,
                "pages": gallery.pages,
                "cover_thumb": cover_map.get(gallery.id),
                "logical_bytes": logical_sizes.get(gallery.id, 0),
                "unique_cas_bytes": unique_sizes.get(gallery.id, 0),
                "is_favorited": gallery.id in favorite_set,
                "my_rating": rating_map.get(gallery.id),
                "in_reading_list": gallery.id in reading_set,
                "deleted_at": gallery.deleted_at,
            }
            for gallery in galleries
        ],
    }


@router.post("/selections", status_code=201)
async def create_query_selection(
    request: CreateSelectionRequest,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Materialize all accessible Gallery ids for query-wide selection."""
    spec = await normalize_explorer_query(
        db,
        ExplorerQuerySpec(
            node_kind=request.query.node_kind,
            node_id=request.query.node_id,
            query=request.query.query,
            sort=request.query.sort,
            direction=request.query.direction,
        ),
        auth,
    )
    statement = build_explorer_gallery_query(spec, auth).with_only_columns(Gallery.id).order_by(None).limit(20_001)
    gallery_ids = list((await db.execute(statement)).scalars())
    if len(gallery_ids) > 20_000:
        raise HTTPException(status_code=413, detail="Query selection exceeds the 20,000 gallery limit")
    token = str(uuid.uuid4())
    payload = {
        "user_id": auth["user_id"],
        "gallery_ids": gallery_ids,
        "created_from": request.query.model_dump(exclude={"offset", "limit"}),
    }
    redis = get_redis()
    await redis.setex(f"explorer:selection:{token}", 1800, json.dumps(payload))
    return {"selection_token": token, "count": len(gallery_ids), "expires_in": 1800}


async def _enqueue_folder_stats(library_id: int, relative_path: str) -> None:
    import core.queue

    try:
        await core.queue.enqueue(
            "explorer_folder_stats_job",
            _job_id=folder_stats_job_id(library_id, relative_path),
            _timeout=3600,
            library_id=library_id,
            relative_path=relative_path,
        )
    except Exception:
        # Navigation remains usable if the worker is unavailable; the UI keeps
        # the size in a pending state and can request a refresh later.
        return


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
            "saved_searches": {
                "count": saved_search_count,
                "items": [{"id": row.id, "name": row.name, "query": row.query} for row in saved_search_rows],
            },
            "smart_views": {
                "missing_metadata": missing_metadata_count,
                "empty_galleries": empty_count,
                "duplicate_pairs": duplicate_count,
                "trash": True,
            },
        },
        "physical": physical,
    }


@router.get("/physical/{library_id}/entries")
async def physical_entries(
    library_id: int,
    path: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """List safe direct children without exposing the configured host path."""
    library = await db.get(LibraryPath, library_id)
    if library is None or not library.enabled:
        raise HTTPException(status_code=404, detail="Library path not found")
    root = Path(library.path).resolve(strict=False)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Library path is unavailable")
    directory = resolve_library_relative(root, path, require_directory=True)
    canonical_path = relative_posix(root, directory)

    entries: list[tuple[int, str, Path, Path]] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        raise HTTPException(status_code=403, detail="Library directory is not readable")
    for child in children:
        try:
            resolved = child.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_relative_to(root):
            continue
        if resolved.is_dir():
            entries.append((0, child.name.casefold(), child, resolved))
        elif resolved.is_file() and resolved.suffix.lower() in MEDIA_EXTENSIONS:
            entries.append((1, child.name.casefold(), child, resolved))
    entries.sort(key=lambda item: (item[0], item[1]))
    total = len(entries)
    page = entries[offset : offset + limit]

    directory_paths = [str(resolved) for kind, _, _, resolved in page if kind == 0]
    imported = {}
    if directory_paths:
        imported = {
            row.source_path: row.id
            for row in (
                await db.execute(
                    select(Gallery.source_path, Gallery.id).where(
                        Gallery.source == "local",
                        Gallery.source_path.in_(directory_paths),
                        Gallery.deleted_at.is_(None),
                    )
                )
            ).all()
        }

    redis = get_redis()
    result: list[dict[str, Any]] = []
    enqueue_tasks = []
    for kind, _, child, resolved in page:
        relative = relative_posix(root, resolved)
        stat = resolved.stat()
        if kind == 0:
            stats = await read_folder_stats(redis, library_id, relative)
            if stats is None:
                enqueue_tasks.append(_enqueue_folder_stats(library_id, relative))
            try:
                has_children = any(
                    entry.is_dir() or entry.suffix.lower() in MEDIA_EXTENSIONS for entry in resolved.iterdir()
                )
            except OSError:
                has_children = False
            result.append(
                {
                    "kind": "folder",
                    "name": child.name,
                    "path": relative,
                    "has_children": has_children,
                    "gallery_id": imported.get(str(resolved)),
                    "size_status": "ready" if stats else "pending",
                    "physical_bytes": stats.get("physical_bytes") if stats else None,
                    "media_count": stats.get("media_count") if stats else None,
                    "size_updated_at": stats.get("updated_at") if stats else None,
                    "modified_at": stat.st_mtime,
                }
            )
        else:
            result.append(
                {
                    "kind": "media",
                    "name": child.name,
                    "path": relative,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    if enqueue_tasks:
        await asyncio.gather(*enqueue_tasks)
    current_stats = await read_folder_stats(redis, library_id, canonical_path)
    if current_stats is None:
        await _enqueue_folder_stats(library_id, canonical_path)
    return {
        "library_id": library_id,
        "path": canonical_path,
        "read_only": True,
        "total": total,
        "entries": result,
        "folder_stats": current_stats,
        "size_status": "ready" if current_stats else "pending",
    }


@router.get("/physical/{library_id}/preview")
async def physical_preview(
    library_id: int,
    path: str = Query(min_length=1),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Serve a validated raw media file inside a configured LibraryPath."""
    library = await db.get(LibraryPath, library_id)
    if library is None or not library.enabled:
        raise HTTPException(status_code=404, detail="Library path not found")
    root = Path(library.path).resolve(strict=False)
    media_path = resolve_library_relative(root, path, require_directory=False)
    if media_path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    media_type = detect_media_type(media_path)
    if media_type is None:
        raise HTTPException(status_code=415, detail="Media signature does not match a supported type")
    return FileResponse(media_path, media_type=media_type, filename=media_path.name, content_disposition_type="inline")


@router.post("/physical/{library_id}/refresh-size")
async def refresh_physical_size(
    library_id: int,
    path: str = Query(default=""),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    library = await db.get(LibraryPath, library_id)
    if library is None or not library.enabled:
        raise HTTPException(status_code=404, detail="Library path not found")
    root = Path(library.path).resolve(strict=False)
    directory = resolve_library_relative(root, path, require_directory=True)
    canonical_path = relative_posix(root, directory)
    redis = get_redis()
    await redis.delete(folder_stats_key(library_id, canonical_path))
    await _enqueue_folder_stats(library_id, canonical_path)
    return {"status": "queued", "path": canonical_path}


@router.post("/physical/{library_id}/import")
async def import_physical_folder(
    library_id: int,
    path: str = Query(min_length=1),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Queue safe discovery/import for one raw folder under a LibraryPath."""
    import core.queue

    library = await db.get(LibraryPath, library_id)
    if library is None or not library.enabled:
        raise HTTPException(status_code=404, detail="Library path not found")
    root = Path(library.path).resolve(strict=False)
    directory = resolve_library_relative(root, path, require_directory=True)
    canonical_path = relative_posix(root, directory)
    try:
        has_media = any(entry.is_file() and entry.suffix.lower() in MEDIA_EXTENSIONS for entry in directory.iterdir())
    except OSError:
        raise HTTPException(status_code=403, detail="Library directory is not readable")
    if not has_media:
        raise HTTPException(status_code=400, detail="The folder has no directly contained supported media")
    job = await core.queue.enqueue(
        "rescan_by_path_job",
        _job_id=f"explorer-import-{library_id}-{folder_stats_job_id(library_id, canonical_path)}",
        _timeout=3600,
        dir_path=str(directory),
    )
    return {"status": "queued", "path": canonical_path, "job_id": getattr(job, "id", None)}


@router.post("/operations/metadata")
async def bulk_edit_metadata(
    request: BulkMetadataRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Apply explicit tri-state scalar edits and record one durable operation."""
    effective = {name: (change.mode, change.value) for name, change in request.fields.items() if change.mode != "keep"}
    if not effective:
        raise HTTPException(status_code=400, detail="No metadata changes were requested")

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="metadata",
        status="running",
        selection_count=len(galleries),
        params={
            "gallery_ids": [gallery.id for gallery in galleries],
            "fields": {name: {"mode": mode, "value": value} for name, (mode, value) in effective.items()},
            "lock_fields": request.lock_fields,
        },
    )
    db.add(operation)
    changed_count = await apply_manual_scalar_changes(
        db,
        galleries,
        effective,
        actor_user_id=auth["user_id"],
        operation_id=operation.id,
        lock_fields=request.lock_fields,
    )
    operation.status = "completed"
    operation.progress = {"processed": len(galleries), "changed_fields": changed_count}
    from datetime import UTC, datetime

    operation.started_at = operation.created_at or datetime.now(UTC)
    operation.finished_at = datetime.now(UTC)
    await db.commit()

    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        gallery_ids=[gallery.id for gallery in galleries],
        action="metadata",
    )
    return {
        "operation_id": str(operation.id),
        "status": operation.status,
        "selection_count": len(galleries),
        "changed_fields": changed_count,
    }


@router.post("/operations/delete")
async def bulk_delete_galleries(
    request: BulkDeleteRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Move an explicit or query-wide Gallery selection to Trash."""
    from datetime import UTC, datetime

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    active_ids = set(
        (
            await db.execute(
                select(DownloadJob.gallery_id).where(
                    DownloadJob.gallery_id.in_(gallery_ids),
                    DownloadJob.status.in_(("queued", "running", "paused")),
                )
            )
        ).scalars()
    )
    now = datetime.now(UTC)
    affected = [gallery for gallery in galleries if gallery.id not in active_ids]
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="delete",
        status="completed",
        selection_count=len(galleries),
        params={"gallery_ids": gallery_ids, "destination": "trash"},
        progress={"affected": len(affected), "skipped_active_downloads": sorted(active_ids)},
        started_at=now,
        finished_at=now,
    )
    db.add(operation)
    for gallery in affected:
        gallery.deleted_at = now
    await db.commit()
    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action="delete",
        gallery_ids=[gallery.id for gallery in affected],
    )
    return {
        "operation_id": str(operation.id),
        "status": "completed",
        "affected": len(affected),
        "skipped_active_downloads": sorted(active_ids),
    }


@router.post("/operations/action")
async def bulk_gallery_action(
    request: BulkActionRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Apply tag, collection, rating, favorite, or read-later changes."""
    from datetime import UTC, datetime

    from services.tag_helpers import parse_tag_strings

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    if request.action in {
        "favorite",
        "unfavorite",
        "rate",
        "add_read_later",
        "remove_read_later",
        "add_collection",
        "remove_collection",
    }:
        galleries = await load_accessible_galleries(db, gallery_ids, auth)
    else:
        galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    affected = 0

    if request.action in {"favorite", "unfavorite"}:
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserFavorite).where(
                        UserFavorite.user_id == auth["user_id"], UserFavorite.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        if request.action == "favorite":
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    db.add(UserFavorite(user_id=auth["user_id"], gallery_id=gallery_id))
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
    elif request.action in {"add_read_later", "remove_read_later"}:
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserReadingList).where(
                        UserReadingList.user_id == auth["user_id"], UserReadingList.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        if request.action == "add_read_later":
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    db.add(UserReadingList(user_id=auth["user_id"], gallery_id=gallery_id))
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
    elif request.action == "rate":
        if request.rating is None:
            raise HTTPException(status_code=400, detail="rating is required")
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(UserRating).where(
                        UserRating.user_id == auth["user_id"], UserRating.gallery_id.in_(gallery_ids)
                    )
                )
            ).scalars()
        }
        for gallery_id in gallery_ids:
            row = existing.get(gallery_id)
            if request.rating == 0:
                if row is not None:
                    await db.delete(row)
                    affected += 1
            elif row is None:
                db.add(UserRating(user_id=auth["user_id"], gallery_id=gallery_id, rating=request.rating))
                affected += 1
            elif row.rating != request.rating:
                row.rating = request.rating
                row.rated_at = datetime.now(UTC)
                affected += 1
    elif request.action in {"add_collection", "remove_collection"}:
        if request.collection_id is None:
            raise HTTPException(status_code=400, detail="collection_id is required")
        collection = await db.get(Collection, request.collection_id)
        if collection is None or (auth["role"] != "admin" and collection.user_id != auth["user_id"]):
            raise HTTPException(status_code=404, detail="Collection not found")
        existing = {
            row.gallery_id: row
            for row in (
                await db.execute(
                    select(CollectionGallery).where(
                        CollectionGallery.collection_id == request.collection_id,
                        CollectionGallery.gallery_id.in_(gallery_ids),
                    )
                )
            ).scalars()
        }
        if request.action == "add_collection":
            position = (
                await db.execute(
                    select(func.coalesce(func.max(CollectionGallery.position), -1)).where(
                        CollectionGallery.collection_id == request.collection_id
                    )
                )
            ).scalar_one()
            for gallery_id in gallery_ids:
                if gallery_id not in existing:
                    position += 1
                    db.add(
                        CollectionGallery(collection_id=request.collection_id, gallery_id=gallery_id, position=position)
                    )
                    affected += 1
        else:
            for row in existing.values():
                await db.delete(row)
                affected += 1
        collection.updated_at = datetime.now(UTC)
    else:
        parsed = parse_tag_strings(request.tags)
        if not parsed:
            raise HTTPException(status_code=400, detail="At least one valid tag is required")
        tags = (
            (
                await db.execute(
                    select(Tag).where(
                        or_(*[(Tag.namespace == namespace) & (Tag.name == name) for namespace, name in parsed])
                    )
                )
            )
            .scalars()
            .all()
        )
        by_value = {(tag.namespace, tag.name): tag for tag in tags}
        if request.action == "add_tags":
            for namespace, name in parsed:
                if (namespace, name) not in by_value:
                    tag = Tag(namespace=namespace, name=name, count=0)
                    db.add(tag)
                    await db.flush()
                    by_value[(namespace, name)] = tag
        tag_ids = [tag.id for tag in by_value.values()]
        existing_rows = (
            (
                await db.execute(
                    select(GalleryTag).where(GalleryTag.gallery_id.in_(gallery_ids), GalleryTag.tag_id.in_(tag_ids))
                )
            )
            .scalars()
            .all()
        )
        existing = {(row.gallery_id, row.tag_id): row for row in existing_rows}
        if request.action == "add_tags":
            for gallery_id in gallery_ids:
                for tag_id in tag_ids:
                    if (gallery_id, tag_id) not in existing:
                        db.add(GalleryTag(gallery_id=gallery_id, tag_id=tag_id, confidence=1.0, source="manual"))
                        affected += 1
        else:
            for row in existing_rows:
                if row.source == "manual":
                    await db.delete(row)
                    affected += 1
        await db.flush()
        tag_rows = (
            await db.execute(
                select(GalleryTag.gallery_id, Tag.namespace, Tag.name)
                .join(Tag, Tag.id == GalleryTag.tag_id)
                .where(GalleryTag.gallery_id.in_(gallery_ids))
                .order_by(Tag.namespace, Tag.name)
            )
        ).all()
        tags_by_gallery: dict[int, list[str]] = {gallery_id: [] for gallery_id in gallery_ids}
        for row in tag_rows:
            tags_by_gallery[row.gallery_id].append(f"{row.namespace}:{row.name}")
        for gallery in galleries:
            gallery.tags_array = tags_by_gallery[gallery.id]
        for tag_id in tag_ids:
            count = (
                await db.execute(select(func.count()).select_from(GalleryTag).where(GalleryTag.tag_id == tag_id))
            ).scalar_one()
            tag = next(tag for tag in by_value.values() if tag.id == tag_id)
            tag.count = count

    now = datetime.now(UTC)
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind=request.action,
        status="completed",
        selection_count=len(galleries),
        params=request.model_dump(exclude={"selection_token"}),
        progress={"affected": affected},
        started_at=now,
        finished_at=now,
    )
    db.add(operation)
    await db.commit()
    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action=request.action,
        gallery_ids=gallery_ids,
    )
    return {"operation_id": str(operation.id), "status": "completed", "affected": affected}


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: uuid.UUID,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    operation = await db.get(WorkbenchOperation, operation_id)
    if operation is None or (auth["role"] != "admin" and operation.user_id != auth["user_id"]):
        raise HTTPException(status_code=404, detail="Workbench operation not found")
    return {
        "id": str(operation.id),
        "kind": operation.kind,
        "status": operation.status,
        "selection_count": operation.selection_count,
        "progress": operation.progress,
        "error": operation.error,
        "created_at": operation.created_at,
        "started_at": operation.started_at,
        "finished_at": operation.finished_at,
    }


@router.post("/merge/preview")
async def preview_merge(
    request: MergeRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Return conflicts and image dedup effects without mutating galleries."""
    from services.workbench_merge import preview_gallery_merge

    return await preview_gallery_merge(db, request.gallery_ids, request.target_id, auth)


@router.post("/merge")
async def merge_galleries(
    request: MergeRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Copy source references into the target and move sources to Trash."""
    from datetime import UTC, datetime

    from core.audit import log_audit
    from services.workbench_merge import execute_gallery_merge

    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="merge",
        status="running",
        selection_count=len(set(request.gallery_ids)),
        params={
            "gallery_ids": request.gallery_ids,
            "target_id": request.target_id,
            "scalar_sources": request.scalar_sources,
            "source_routes": "404",
        },
        started_at=datetime.now(UTC),
    )
    db.add(operation)
    result = await execute_gallery_merge(
        db,
        request.gallery_ids,
        request.target_id,
        request.scalar_sources,
        auth,
        operation.id,
    )
    operation.status = "completed"
    operation.progress = result
    operation.finished_at = datetime.now(UTC)
    await db.commit()

    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action="merge",
        **result,
    )
    await log_audit(
        auth["user_id"],
        "gallery.merge",
        f"target={result['target_id']} sources={result['source_ids']} source_routes=404",
    )
    return {"operation_id": str(operation.id), "status": operation.status, **result}


@router.get("/galleries/{gallery_id}/metadata-history")
async def metadata_history(
    gallery_id: int,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    from core.auth import gallery_access_filter
    from db.models import Gallery

    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")

    states = (
        (await db.execute(select(GalleryMetadataFieldState).where(GalleryMetadataFieldState.gallery_id == gallery_id)))
        .scalars()
        .all()
    )
    changes = (
        (
            await db.execute(
                select(GalleryMetadataChange)
                .where(GalleryMetadataChange.gallery_id == gallery_id)
                .order_by(desc(GalleryMetadataChange.created_at), desc(GalleryMetadataChange.id))
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return {
        "gallery_id": gallery_id,
        "fields": {
            state.field_name: {
                "origin": state.origin,
                "locked": state.locked,
                "source_value": state.source_value,
                "updated_at": state.updated_at,
            }
            for state in states
        },
        "changes": [
            {
                "id": change.id,
                "field": change.field_name,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "origin": change.origin,
                "actor_user_id": change.actor_user_id,
                "operation_id": str(change.operation_id) if change.operation_id else None,
                "created_at": change.created_at,
            }
            for change in changes
        ],
    }
