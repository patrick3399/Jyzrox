"""Library path management and monitor endpoints."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import core.queue
from core.auth import require_role
from core.config import get_all_library_paths, settings
from core.database import async_session
from core.local_patterns import (
    DEFAULT_IMPORT_MODE,
    DEFAULT_LIBRARY_PATTERN,
    PatternError,
    display_library_pattern,
    split_library_pattern_path,
)
from core.redis_client import get_redis
from db.models import Gallery, LibraryPath

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


@router.get("/libraries")
async def list_libraries(_: dict = Depends(_member)):
    """List all library paths (primary + extras from env + DB-stored)."""
    all_paths = await get_all_library_paths()

    async with async_session() as session:
        result = await session.execute(select(LibraryPath).order_by(LibraryPath.added_at))
        db_paths = result.scalars().all()

        # Count galleries per library_path
        count_rows = await session.execute(
            select(Gallery.library_path, func.count(Gallery.id))
            .where(Gallery.library_path.isnot(None))
            .group_by(Gallery.library_path)
        )
        gallery_counts = {row[0]: row[1] for row in count_rows}

    db_map = {lp.path: lp for lp in db_paths}

    libraries = []
    for p in all_paths:
        lp = db_map.get(p)
        libraries.append(
            {
                "id": lp.id if lp else None,
                "path": p,
                "label": lp.label if lp else Path(p).name,
                "pattern": lp.pattern if lp else DEFAULT_LIBRARY_PATTERN,
                "import_mode": lp.import_mode if lp else DEFAULT_IMPORT_MODE,
                "display_pattern": display_library_pattern(
                    p,
                    lp.pattern if lp else DEFAULT_LIBRARY_PATTERN,
                ),
                "enabled": lp.enabled if lp else True,
                "monitor": lp.monitor if lp else True,
                "exists": Path(p).is_dir(),
                "added_at": str(lp.added_at) if lp else None,
                "gallery_count": gallery_counts.get(p, 0),
            }
        )
    return libraries


class AddLibraryRequest(BaseModel):
    path: str
    label: str | None = None
    import_mode: str = DEFAULT_IMPORT_MODE


async def _watcher_enabled() -> bool:
    """Return the admin's stored watcher choice, or the startup default if none is stored."""
    raw = await get_redis().get("watcher:enabled")
    return settings.library_monitor_enabled if raw is None else raw not in (b"0", "0")


async def _refresh_watcher_paths() -> None:
    """Have the worker re-read its monitored paths, unless the admin turned the watcher off.

    Best-effort: the library row is already committed, and the worker reads the
    paths again whenever it starts.
    """
    try:
        if await _watcher_enabled():
            await core.queue.enqueue("toggle_watcher_job", enabled=True)
    except Exception as exc:
        logger.warning("Could not refresh the library watcher: %s", exc)


@router.post("/libraries")
async def add_library(req: AddLibraryRequest, _: dict = Depends(_admin)):
    """Add a new library path."""
    if req.import_mode not in ("link", "copy"):
        raise HTTPException(status_code=400, detail="import_mode must be 'link' or 'copy'")
    try:
        parsed = split_library_pattern_path(req.path)
    except PatternError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    real_path = parsed.root_path
    if not Path(real_path).is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")

    async with async_session() as session:
        stmt = (
            pg_insert(LibraryPath)
            .values(
                path=real_path,
                label=req.label or Path(real_path).name,
                pattern=parsed.pattern,
                import_mode=req.import_mode,
            )
            .on_conflict_do_update(
                index_elements=["path"],
                set_={
                    "label": req.label or Path(real_path).name,
                    "pattern": parsed.pattern,
                    "import_mode": req.import_mode,
                    "enabled": True,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

    await _refresh_watcher_paths()

    return {
        "status": "added",
        "path": real_path,
        "pattern": parsed.pattern,
        "import_mode": req.import_mode,
        "display_pattern": parsed.display_pattern,
    }


@router.delete("/libraries/{library_id}")
async def remove_library(library_id: int, _: dict = Depends(_admin)):
    """Remove a library path (does not delete files or galleries)."""
    async with async_session() as session:
        lp = await session.get(LibraryPath, library_id)
        if not lp:
            raise HTTPException(status_code=404, detail="Library path not found")
        await session.delete(lp)
        await session.commit()

    await _refresh_watcher_paths()
    return {"status": "removed"}


# ── Monitor Status ────────────────────────────────────────────────────


@router.get("/monitor/status")
async def monitor_status(_: dict = Depends(_member)):
    """Return file watcher status (sourced from Redis, set by the worker process)."""
    r = get_redis()
    enabled = await _watcher_enabled()
    data = await r.get("watcher:status")
    if not data:
        return {
            "enabled": enabled,
            "running": False,
            "watched_paths": [],
        }
    parsed = json.loads(data)
    return {
        "enabled": enabled,
        "running": parsed.get("running", False),
        "watched_paths": parsed.get("paths", []),
    }


class MonitorToggleRequest(BaseModel):
    enabled: bool


@router.post("/monitor/toggle")
async def toggle_monitor(
    req: MonitorToggleRequest,
    request: Request,
    _: dict = Depends(_admin),
):
    """Toggle the file system watcher on/off.

    Sets the ``watcher:enabled`` Redis key to persist the desired state across
    worker restarts, then enqueues ``toggle_watcher_job`` so the running worker
    acts on the change immediately.
    """
    r = get_redis()
    await r.set("watcher:enabled", "1" if req.enabled else "0")
    # Update status immediately so the UI reflects the change before the
    # worker job finishes executing.
    current = await r.get("watcher:status")
    paths = json.loads(current).get("paths", []) if current else []
    await r.set("watcher:status", json.dumps({"running": req.enabled, "paths": paths if req.enabled else []}))
    await core.queue.enqueue("toggle_watcher_job", enabled=req.enabled)
    return {"status": "enabled" if req.enabled else "disabled"}
