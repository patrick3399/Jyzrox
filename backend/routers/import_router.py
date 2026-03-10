"""Gallery import handling (Link and Copy modes)."""

import json
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth
from core.config import get_all_library_paths, settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import Gallery, LibraryPath

router = APIRouter(tags=["import"])


class BatchScanRequest(BaseModel):
    root_dir: str
    pattern: str = "{title}"


class BatchStartRequest(BaseModel):
    root_dir: str
    mode: str = "copy"  # "copy" | "link"
    galleries: list[dict]  # [{path, artist, title}, ...]


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

    if not any(
        real_root == rp or real_root.startswith(rp + os.sep)
        for rp in allowed_real
    ):
        raise HTTPException(status_code=400, detail="root_dir must be within a configured library path")

    if not os.path.isdir(real_root):
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")
    if not os.access(real_root, os.R_OK):
        raise HTTPException(status_code=400, detail="Path is not readable")

    return real_root


def _build_pattern_regex(pattern: str) -> re.Pattern:
    """Build a full-match regex from a pattern string with {name} placeholders."""
    parts = re.split(r'(\{[^}]+\})', pattern)
    regex_parts = []
    for part in parts:
        if part.startswith('{') and part.endswith('}'):
            name = part[1:-1]
            if name == '_':
                regex_parts.append(r'(?:[^/]+)')
            else:
                regex_parts.append(rf'(?P<{name}>[^/]+)')
        else:
            regex_parts.append(re.escape(part))
    return re.compile('^' + ''.join(regex_parts) + '$')


@router.post("/batch/scan")
async def batch_scan(
    req: BatchScanRequest,
    _: dict = Depends(require_auth),
):
    """Scan root_dir using pattern to find importable gallery directories."""
    real_root = await _validate_root_dir(req.root_dir)
    pattern_re = _build_pattern_regex(req.pattern)

    matches = []
    unmatched = []

    for dirpath, dirnames, filenames in os.walk(real_root):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]

        media_files = [f for f in filenames if Path(f).suffix.lower() in _SUPPORTED_EXTS]
        if not media_files:
            continue

        abs_path = dirpath
        try:
            rel_path = os.path.relpath(abs_path, real_root)
        except ValueError:
            continue

        # Skip root itself
        if rel_path == '.':
            continue

        # Normalize path separators
        rel_path_normalized = rel_path.replace(os.sep, '/')

        m = pattern_re.match(rel_path_normalized)
        if m:
            groups = m.groupdict()
            artist = groups.get('artist') or None
            title = groups.get('title') or Path(abs_path).name
            matches.append({
                "rel_path": rel_path_normalized,
                "abs_path": abs_path,
                "artist": artist,
                "title": title,
                "file_count": len(media_files),
            })
        else:
            unmatched.append({
                "rel_path": rel_path_normalized,
                "file_count": len(media_files),
            })

    return {"matches": matches, "unmatched": unmatched}


@router.post("/batch/start")
async def batch_start(
    req: BatchStartRequest,
    request: Request,
    _: dict = Depends(require_auth),
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
        json.dumps({
            "total": total,
            "completed": 0,
            "failed": 0,
            "status": "running",
            "current_gallery_id": None,
        }),
    )

    # If link mode, auto-register root_dir as a library path
    if req.mode == "link":
        async with async_session() as session:
            stmt = pg_insert(LibraryPath).values(
                path=real_root,
                label=Path(real_root).name,
            ).on_conflict_do_nothing()
            await session.execute(stmt)
            await session.commit()

    arq = request.app.state.arq
    await arq.enqueue_job("batch_import_job", real_root, req.mode, req.galleries, batch_id)

    return {"batch_id": batch_id, "total": total}


@router.get("/batch/progress/{batch_id}")
async def batch_progress(
    batch_id: str,
    _: dict = Depends(require_auth),
):
    """Get progress for an ongoing or completed batch import."""
    r = get_redis()
    data = await r.get(f"import:batch:{batch_id}")
    if not data:
        return {"status": "unknown"}
    return json.loads(data)


@router.get("/progress/{gallery_id}")
async def get_import_progress(
    gallery_id: int,
    _: dict = Depends(require_auth),
):
    """Poll import progress for a gallery."""
    r = get_redis()
    data = await r.get(f"import:progress:{gallery_id}")
    if not data:
        return {"gallery_id": gallery_id, "status": "unknown"}
    return {"gallery_id": gallery_id, **json.loads(data)}


_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}


@router.get("/browse")
async def browse_directory(path: str = "", library: str = "", _: dict = Depends(require_auth)):
    """List directories and image files within a library path.

    The ``library`` param selects which library root to browse (must be one of
    the configured library paths). If omitted, the primary gallery path is used.
    """
    # Determine and validate the base library path
    all_paths = await get_all_library_paths()

    if library:
        real_lib = os.path.realpath(library)
        allowed = [os.path.realpath(p) for p in all_paths]
        # Also allow the base path itself even if the directory doesn't exist yet
        if os.path.realpath(settings.library_base_path) not in allowed:
            allowed.append(os.path.realpath(settings.library_base_path))
        if real_lib not in allowed:
            raise HTTPException(status_code=400, detail="Library path not in configured paths")
        base = Path(real_lib)
    else:
        base = Path(settings.library_base_path)

    target = (base / path).resolve()

    # Security: use os.path.realpath to prevent path traversal via symlinks.
    real_base = os.path.realpath(str(base))
    real_target = os.path.realpath(str(target))
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail="Path outside allowed directory")

    # Block any path that resolves inside the internal download directory.
    real_data = os.path.realpath(settings.data_gallery_path)
    if real_target == real_data or real_target.startswith(real_data + os.sep):
        raise HTTPException(
            status_code=400,
            detail="Browsing the internal download directory is not allowed",
        )
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    try:
        items = sorted(target.iterdir(), key=lambda x: x.name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {exc}") from exc

    for item in items:
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                file_count = sum(
                    1 for f in item.iterdir()
                    if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS
                )
            except OSError:
                file_count = 0
            entries.append({"name": item.name, "type": "dir", "file_count": file_count})
        elif item.is_file() and item.suffix.lower() in _SUPPORTED_EXTS:
            try:
                size = item.stat().st_size
            except OSError:
                size = 0
            entries.append({"name": item.name, "type": "file", "size": size})

    # Mark directories that are already imported
    if entries:
        dir_names = [e["name"] for e in entries if e["type"] == "dir"]
        if dir_names:
            async with async_session() as session:
                result = await session.execute(
                    select(Gallery.source_id).where(Gallery.source_id.in_(dir_names))
                )
                imported_ids = {row[0] for row in result.fetchall()}
            for e in entries:
                if e["type"] == "dir":
                    e["imported"] = e["name"] in imported_ids

    return {"path": path or "/", "base": str(base), "library": str(base), "entries": entries}


@router.get("/mount-points")
async def list_mount_points(_: dict = Depends(require_auth)):
    """List meaningful mount points in the container (similar to Jellyfin's GetDrives).

    Filters out virtual/system filesystems to show only user-relevant mounts
    like /mnt/xxx, /data, /config, etc.
    """
    import psutil

    # Filesystem types to exclude (virtual/system)
    exclude_fs = {
        'proc', 'sysfs', 'devpts', 'tmpfs', 'cgroup', 'cgroup2', 'overlay',
        'mqueue', 'devtmpfs', 'hugetlbfs', 'securityfs', 'pstore',
        'debugfs', 'tracefs', 'fusectl', 'configfs', 'nsfs',
        'autofs', 'binfmt_misc', 'efivarfs',
    }
    # Mount points to exclude
    exclude_paths = {'/', '/proc', '/sys', '/dev', '/run', '/tmp',
                     '/etc/resolv.conf', '/etc/hostname', '/etc/hosts'}

    mounts = []
    for p in psutil.disk_partitions(all=True):
        if p.fstype in exclude_fs:
            continue
        if p.mountpoint in exclude_paths:
            continue
        # Skip /dev/* mounts
        if p.mountpoint.startswith('/dev/'):
            continue
        if not os.path.isdir(p.mountpoint):
            continue
        mounts.append({
            "name": Path(p.mountpoint).name or p.mountpoint,
            "path": p.mountpoint,
            "type": "dir",
        })

    # Sort by path for consistent ordering
    mounts.sort(key=lambda m: m["path"])
    return {"mounts": mounts}


@router.get("/browse-fs")
async def browse_filesystem(path: str = "/mnt", _: dict = Depends(require_auth)):
    """Browse container filesystem for selecting library paths.

    Unlike /browse (which is restricted to configured library paths),
    this endpoint allows navigating any safe directory in the container
    to help users discover mount points when adding new library paths.
    """
    target = Path(path).resolve()
    real_target = os.path.realpath(str(target))

    # Block sensitive paths
    blocked = ["/proc", "/sys", "/dev", "/etc", "/var", "/usr", "/bin", "/sbin",
               "/lib", "/root", "/tmp", "/run", "/boot", "/srv",
               os.path.realpath(settings.data_gallery_path)]
    for b in blocked:
        if real_target == b or real_target.startswith(b + os.sep):
            raise HTTPException(status_code=400, detail="Cannot browse this path")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    try:
        items = sorted(target.iterdir(), key=lambda x: x.name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list: {exc}") from exc

    for item in items:
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append({"name": item.name, "type": "dir"})

    # Build parent path for navigation
    parent = str(target.parent) if str(target) != "/" else None

    return {
        "path": str(target),
        "parent": parent,
        "entries": entries,
    }


@router.get("/recent")
async def recent_imports(_: dict = Depends(require_auth)):
    """Return the 20 most recently added local galleries."""
    async with async_session() as session:
        result = await session.execute(
            select(Gallery)
            .where(Gallery.source == "local")
            .order_by(desc(Gallery.added_at))
            .limit(20)
        )
        galleries = result.scalars().all()
    return [
        {
            "id": g.id,
            "title": g.title,
            "pages": g.pages,
            "status": g.download_status,
            "added_at": str(g.added_at),
        }
        for g in galleries
    ]


# NOTE: /rescan/status is defined BEFORE /rescan/{gallery_id} so FastAPI does
# not attempt to coerce the literal string "status" into an integer gallery_id.
@router.get("/rescan/status")
async def rescan_status(_: dict = Depends(require_auth)):
    """Return current rescan progress stored in Redis."""
    r = get_redis()
    data = await r.get("rescan:progress")
    if not data:
        return {"running": False}
    parsed = json.loads(data)
    is_running = parsed.get("status") == "running"
    return {"running": is_running, **parsed}


@router.post("/rescan")
async def rescan_library(request: Request, _: dict = Depends(require_auth)):
    """Enqueue a full library rescan job."""
    arq = request.app.state.arq
    await arq.enqueue_job("rescan_library_job")
    return {"status": "enqueued"}


# NOTE: /rescan/cancel must be defined BEFORE /rescan/{gallery_id} so FastAPI
# does not attempt to coerce the literal string "cancel" into an integer gallery_id.
@router.post("/rescan/cancel")
async def cancel_rescan(_: dict = Depends(require_auth)):
    """Signal the running rescan to stop at the next gallery boundary."""
    r = get_redis()
    await r.set("rescan:cancel", "1", ex=300)  # expires in 5 min as safety net
    return {"status": "cancelling"}


@router.post("/rescan/path/{library_id}")
async def rescan_library_path(library_id: int, request: Request, _: dict = Depends(require_auth)):
    """Enqueue rescan for all galleries under a specific library path.

    NOTE: defined BEFORE /rescan/{gallery_id} so FastAPI does not attempt to
    coerce the literal string "path" into an integer gallery_id.
    """
    async with async_session() as session:
        lp = await session.get(LibraryPath, library_id)
        if not lp:
            raise HTTPException(404, "Library path not found")
    arq = request.app.state.arq
    await arq.enqueue_job("rescan_library_path_job", lp.path)
    return {"status": "enqueued", "path": lp.path}


@router.post("/rescan/{gallery_id}")
async def rescan_gallery(
    gallery_id: int,
    request: Request,
    _: dict = Depends(require_auth),
):
    """Enqueue a rescan job for a single gallery."""
    arq = request.app.state.arq
    await arq.enqueue_job("rescan_gallery_job", gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}


# ── Scan Schedule ────────────────────────────────────────────────────


class ScanScheduleRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = None


@router.get("/scan-settings")
async def get_scan_settings(_: dict = Depends(require_auth)):
    """Return current scan schedule settings."""
    r = get_redis()
    enabled = await r.get("scan:schedule:enabled")
    interval = await r.get("scan:schedule:interval_hours")
    last_run = await r.get("scan:schedule:last_run")
    return {
        "enabled": enabled != b"0" if enabled is not None else True,
        "interval_hours": int(interval) if interval else settings.library_scan_interval_hours,
        "last_run": last_run.decode() if last_run else None,
    }


@router.patch("/scan-settings")
async def update_scan_settings(req: ScanScheduleRequest, _: dict = Depends(require_auth)):
    """Update scan schedule settings (stored in Redis)."""
    r = get_redis()
    if req.enabled is not None:
        await r.set("scan:schedule:enabled", "1" if req.enabled else "0")
    if req.interval_hours is not None:
        if req.interval_hours < 6 or req.interval_hours > 168:
            raise HTTPException(400, "Interval must be between 6 and 168 hours")
        await r.set("scan:schedule:interval_hours", str(req.interval_hours))

    # Return updated settings
    return await get_scan_settings(_)


# ── Library Path Management ───────────────────────────────────────────

@router.get("/libraries")
async def list_libraries(_: dict = Depends(require_auth)):
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
        libraries.append({
            "id": lp.id if lp else None,
            "path": p,
            "label": lp.label if lp else Path(p).name,
            "enabled": lp.enabled if lp else True,
            "monitor": lp.monitor if lp else True,
            "exists": Path(p).is_dir(),
            "added_at": str(lp.added_at) if lp else None,
            "gallery_count": gallery_counts.get(p, 0),
        })
    return libraries


class AddLibraryRequest(BaseModel):
    path: str
    label: str | None = None


@router.post("/libraries")
async def add_library(req: AddLibraryRequest, _: dict = Depends(require_auth)):
    """Add a new library path."""
    real_path = os.path.realpath(req.path)
    if not Path(real_path).is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")

    async with async_session() as session:
        stmt = pg_insert(LibraryPath).values(
            path=real_path,
            label=req.label or Path(real_path).name,
        ).on_conflict_do_nothing()
        await session.execute(stmt)
        await session.commit()

    return {"status": "added", "path": real_path}


@router.delete("/libraries/{library_id}")
async def remove_library(library_id: int, _: dict = Depends(require_auth)):
    """Remove a library path (does not delete files or galleries)."""
    async with async_session() as session:
        lp = await session.get(LibraryPath, library_id)
        if not lp:
            raise HTTPException(status_code=404, detail="Library path not found")
        await session.delete(lp)
        await session.commit()
    return {"status": "removed"}


# ── Monitor Status ────────────────────────────────────────────────────

@router.get("/monitor/status")
async def monitor_status(_: dict = Depends(require_auth)):
    """Return file watcher status (sourced from Redis, set by the worker process)."""
    r = get_redis()
    data = await r.get("watcher:status")
    if not data:
        return {
            "enabled": settings.library_monitor_enabled,
            "running": False,
            "watched_paths": [],
        }
    parsed = json.loads(data)
    return {
        "enabled": settings.library_monitor_enabled,
        "running": parsed.get("running", False),
        "watched_paths": parsed.get("paths", []),
    }


class MonitorToggleRequest(BaseModel):
    enabled: bool


@router.post("/monitor/toggle")
async def toggle_monitor(
    req: MonitorToggleRequest,
    request: Request,
    _: dict = Depends(require_auth),
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
    arq = request.app.state.arq
    await arq.enqueue_job("toggle_watcher_job", req.enabled)
    return {"status": "enabled" if req.enabled else "disabled"}
