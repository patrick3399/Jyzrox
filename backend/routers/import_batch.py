"""Batch folder scan/start/progress import endpoints."""

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.auth import require_role
from core.config import get_all_library_paths, settings
from core.database import async_session, get_db
from core.local_patterns import (
    DEFAULT_LIBRARY_PATTERN,
    PatternError,
    build_library_pattern_regex,
)
from core.redis_client import get_redis
from db.models import LibraryPath
from services.gallery_categories import load_category_map, resolve_with_map
from services.media_formats import MEDIA_EXTENSIONS as _SUPPORTED_EXTS

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class BatchScanRequest(BaseModel):
    root_dir: str
    pattern: str = "{title}"


class BatchGalleryItem(BaseModel):
    path: str
    title: str
    artist: str | None = None
    category: str | None = None


class BatchStartRequest(BaseModel):
    root_dir: str
    mode: str = "copy"  # "copy" | "link"
    galleries: list[BatchGalleryItem]  # [{path, artist, category, title}, ...]


async def _validate_root_dir(root_dir: str) -> str:
    """Resolve and validate root_dir against security constraints.

    Returns the resolved real path or raises HTTPException.
    """
    if not os.path.isabs(root_dir):
        root_dir = os.path.join(settings.library_base_path, root_dir)

    real_root = os.path.realpath(root_dir)

    real_data = os.path.realpath(settings.data_gallery_path)
    if real_root.startswith(real_data + os.sep) or real_root == real_data:
        raise HTTPException(
            status_code=400,
            detail="Cannot import from internal download directory. Mount external media under /mnt/",
        )

    all_library_paths = await get_all_library_paths()
    allowed_real = [os.path.realpath(p) for p in all_library_paths]
    allowed_real.append(os.path.realpath(settings.library_base_path))

    if not any(real_root == rp or real_root.startswith(rp + os.sep) for rp in allowed_real):
        raise HTTPException(status_code=400, detail="root_dir must be within a configured library path")

    if not os.path.isdir(real_root):
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")
    if not os.access(real_root, os.R_OK):
        raise HTTPException(status_code=400, detail="Path is not readable")

    return real_root


def _build_pattern_regex(pattern: str) -> re.Pattern:
    """Build a full-match regex from a pattern string with {name} placeholders.

    Security: non-placeholder text is re.escape()d so user content never
    contributes regex metacharacters.  Placeholders are hardcoded to ``[^/]+``.
    """
    try:
        return build_library_pattern_regex(pattern)
    except PatternError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _walk_media_dirs(real_root: str) -> list[tuple[str, list[str]]]:
    """Return (directory, media filenames) for every non-hidden directory holding media."""
    found: list[tuple[str, list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(real_root):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        media_files = [f for f in filenames if Path(f).suffix.lower() in _SUPPORTED_EXTS]
        if media_files:
            found.append((dirpath, media_files))
    return found


@router.post("/batch/scan")
async def batch_scan(
    req: BatchScanRequest,
    _: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Scan root_dir using pattern to find importable gallery directories."""
    real_root = await _validate_root_dir(req.root_dir)
    pattern_re = _build_pattern_regex(req.pattern)

    category_map = await load_category_map(db)
    matches = []
    unmatched = []

    # The walk stats every directory under the root; on a large NFS library
    # that takes seconds, so it runs in a thread instead of on the event loop.
    for dirpath, media_files in await asyncio.to_thread(_walk_media_dirs, real_root):
        abs_path = dirpath
        try:
            rel_path = os.path.relpath(abs_path, real_root)
        except ValueError:
            continue

        # Skip root itself
        if rel_path == ".":
            continue

        # Normalize path separators
        rel_path_normalized = rel_path.replace(os.sep, "/")

        m = pattern_re.match(rel_path_normalized)
        if m:
            groups = m.groupdict()
            artist = groups.get("artist") or None
            category = groups.get("category") or None
            title = groups.get("title") or Path(abs_path).name
            matches.append(
                {
                    "rel_path": rel_path_normalized,
                    "abs_path": abs_path,
                    "artist": artist,
                    "category": category,
                    "category_resolved": resolve_with_map(category, category_map),
                    "title": title,
                    "file_count": len(media_files),
                }
            )
        else:
            unmatched.append(
                {
                    "rel_path": rel_path_normalized,
                    "file_count": len(media_files),
                }
            )

    return {"matches": matches, "unmatched": unmatched}


@router.post("/batch/start")
async def batch_start(
    req: BatchStartRequest,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Start a batch import job for multiple galleries."""
    real_root = await _validate_root_dir(req.root_dir)

    if req.mode not in ("copy", "link"):
        raise HTTPException(status_code=400, detail="mode must be 'copy' or 'link'")

    batch_id = str(uuid.uuid4())
    total = len(req.galleries)

    r = get_redis()
    await r.setex(
        f"import:batch:{batch_id}",
        3600,
        json.dumps(
            {
                "total": total,
                "completed": 0,
                "failed": 0,
                "status": "running",
                "current_gallery_id": None,
            }
        ),
    )
    await r.setex(f"import:batch:{batch_id}:owner", 3600, str(auth["user_id"]))

    # If link mode, auto-register root_dir as a library path
    if req.mode == "link":
        async with async_session() as session:
            stmt = (
                pg_insert(LibraryPath)
                .values(
                    path=real_root,
                    label=Path(real_root).name,
                    pattern=DEFAULT_LIBRARY_PATTERN,
                    import_mode=req.mode,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            await session.commit()

    # SAQ serializes job kwargs to JSON, so BatchGalleryItem instances cannot
    # be passed directly — model_dump() them into plain dicts. category is
    # resolved against the registry here (and again in the worker) so a
    # folder-name-derived or user-supplied value that Pydantic accepts as a
    # `str` but is unusable or unregistered never reaches the job payload.
    category_map = await load_category_map(db)
    galleries_payload = [
        {**g.model_dump(), "category": resolve_with_map(g.category, category_map)} for g in req.galleries
    ]
    await core.queue.enqueue(
        "batch_import_job",
        root_dir=real_root,
        mode=req.mode,
        galleries=galleries_payload,
        batch_id=batch_id,
        user_id=auth["user_id"],
    )

    return {"batch_id": batch_id, "total": total}


@router.get("/batch/progress/{batch_id}")
async def batch_progress(
    batch_id: str,
    auth: dict = Depends(_member),
):
    """Get progress for an ongoing or completed batch import."""
    r = get_redis()
    data = await r.get(f"import:batch:{batch_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    # Admin can see all; others only own batches
    if auth["role"] != "admin":
        owner = await r.get(f"import:batch:{batch_id}:owner")
        if not owner or int(owner) != auth["user_id"]:
            raise HTTPException(status_code=404, detail="Not found")
    return json.loads(data)
