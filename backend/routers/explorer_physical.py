"""Explorer physical-folder browsing endpoints."""

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from core.redis_client import get_redis
from db.models import (
    Gallery,
    LibraryPath,
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
from services.explorer_requests import (
    enqueue_folder_stats as _enqueue_folder_stats,
)

router = APIRouter()
_member = require_role("member")


def _list_physical_children(root: Path, directory: Path) -> list[tuple[int, str, Path, Path]] | None:
    """Sorted (kind, folded name, child, resolved) entries; None if the directory is unreadable."""
    entries: list[tuple[int, str, Path, Path]] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return None
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
    return entries


def _probe_physical_page(page: list[tuple[int, str, Path, Path]]) -> list[tuple[os.stat_result, bool]]:
    """Per page entry: its stat and, for folders, whether it has a sub-folder or media child."""
    facts: list[tuple[os.stat_result, bool]] = []
    for kind, _, _, resolved in page:
        stat = resolved.stat()
        has_children = False
        if kind == 0:
            try:
                has_children = any(
                    entry.is_dir() or entry.suffix.lower() in MEDIA_EXTENSIONS for entry in resolved.iterdir()
                )
            except OSError:
                has_children = False
        facts.append((stat, has_children))
    return facts


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

    # NFS listing and stats block; run them in threads so the event loop stays free.
    listing = await asyncio.to_thread(_list_physical_children, root, directory)
    if listing is None:
        raise HTTPException(status_code=403, detail="Library directory is not readable")
    entries = listing
    total = len(entries)
    page = entries[offset : offset + limit]
    page_facts = await asyncio.to_thread(_probe_physical_page, page)

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
    for (kind, _, child, resolved), (stat, has_children) in zip(page, page_facts, strict=True):
        relative = relative_posix(root, resolved)
        if kind == 0:
            stats = await read_folder_stats(redis, library_id, relative)
            if stats is None:
                enqueue_tasks.append(_enqueue_folder_stats(library_id, relative))
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


def _has_direct_media(directory: Path) -> bool:
    return any(entry.is_file() and entry.suffix.lower() in MEDIA_EXTENSIONS for entry in directory.iterdir())


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
        has_media = await asyncio.to_thread(_has_direct_media, directory)
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
