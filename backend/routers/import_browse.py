"""Mount-point listing, filesystem browsing and recent imports endpoints."""

import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select

from core.auth import require_role
from core.config import settings
from core.database import async_session
from core.utils import MOUNT_EXCLUDE_FS, MOUNT_EXCLUDE_PATHS
from db.models import Gallery

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


@router.get("/mount-points")
async def list_mount_points(_: dict = Depends(_member)):
    """List meaningful mount points in the container (similar to Jellyfin's GetDrives).

    Filters out virtual/system filesystems to show only user-relevant mounts
    like /mnt/xxx, /data, /config, etc.
    """
    import psutil

    mounts = []
    for p in psutil.disk_partitions(all=True):
        if p.fstype in MOUNT_EXCLUDE_FS:
            continue
        if p.mountpoint in MOUNT_EXCLUDE_PATHS:
            continue
        # Skip /dev/* mounts
        if p.mountpoint.startswith("/dev/"):
            continue
        if not os.path.isdir(p.mountpoint):
            continue
        mounts.append(
            {
                "name": Path(p.mountpoint).name or p.mountpoint,
                "path": p.mountpoint,
                "type": "dir",
            }
        )

    # Sort by path for consistent ordering
    mounts.sort(key=lambda m: m["path"])
    return {"mounts": mounts}


@router.get("/browse-fs")
async def browse_filesystem(path: str = "/mnt", _: dict = Depends(_member)):
    """Browse container filesystem for selecting library paths.

    Unlike /browse (which is restricted to configured library paths),
    this endpoint allows navigating any safe directory in the container
    to help users discover mount points when adding new library paths.
    """
    target = Path(path).resolve()
    real_target = os.path.realpath(str(target))

    # Block sensitive paths
    blocked = [
        "/proc",
        "/sys",
        "/dev",
        "/etc",
        "/var",
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/root",
        "/tmp",
        "/run",
        "/boot",
        "/srv",
        "/app",
        "/data/avatars",
        "/data/training",
        os.path.realpath(settings.data_gallery_path),
        os.path.realpath(settings.data_cas_path),
        os.path.realpath(settings.data_thumbs_path),
        os.path.realpath(settings.data_library_path),
    ]
    for b in blocked:
        if real_target == b or real_target.startswith(b + os.sep):
            raise HTTPException(status_code=400, detail="Cannot browse this path")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    def _list_subdirs() -> list[dict[str, str]]:
        found = []
        for item in sorted(target.iterdir(), key=lambda x: x.name):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                found.append({"name": item.name, "type": "dir"})
        return found

    # Listing and is_dir per entry hit NFS; keep them off the event loop.
    try:
        entries = await asyncio.to_thread(_list_subdirs)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list: {exc}") from exc

    # Build parent path for navigation
    parent = str(target.parent) if str(target) != "/" else None

    return {
        "path": str(target),
        "parent": parent,
        "entries": entries,
    }


@router.get("/recent")
async def recent_imports(auth: dict = Depends(_member)):
    """Return the 20 most recently added local galleries."""
    from core.auth import gallery_access_filter

    async with async_session() as session:
        result = await session.execute(
            select(Gallery)
            .where(Gallery.source == "local", gallery_access_filter(auth))
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
