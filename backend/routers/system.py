import asyncio
import logging
import os
import shutil
import sys

import fastapi
import psutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from core.auth import require_auth, require_role
from core.config import settings
from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from core.utils import MOUNT_EXCLUDE_FS, MOUNT_EXCLUDE_PATHS
from core.version import __version__
from routers import system_cache, system_ops

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

_admin = require_role("admin")


# ── Static version detection (executed once at import time) ───────────


def _detect_python_version() -> str:
    """Return Python version string (major.minor.micro)."""
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


_STATIC_VERSIONS: dict[str, str | None] = {
    "jyzrox": __version__,
    "python": _detect_python_version(),
    "fastapi": fastapi.__version__,
}


# ── Dynamic version helpers (queried per request) ─────────────────────


async def _get_postgresql_version() -> str | None:
    """Query PostgreSQL server version via SELECT version()."""
    try:
        async with AsyncSessionLocal() as session:
            row = await session.execute(text("SELECT version()"))
            raw: str = row.scalar_one()
            # raw looks like "PostgreSQL 15.3 on x86_64-pc-linux-gnu ..."
            # Extract the version number token after "PostgreSQL "
            parts = raw.split()
            if len(parts) >= 2:
                return parts[1]
            return raw
    except Exception as exc:
        logger.warning("Failed to detect PostgreSQL version: %s", exc)
        return None


async def _get_redis_version() -> str | None:
    """Return the server version from INFO server.

    Valkey pins redis_version to 7.2.4 for client compatibility, so its real
    version is in valkey_version.
    """
    try:
        info = await get_redis().info("server")
        return info.get("valkey_version") or info.get("redis_version") or None
    except Exception as exc:
        logger.warning("Failed to detect Redis version: %s", exc)
        return None


@router.get("/health")
async def system_health():
    """Deep health check: verifies PostgreSQL and Redis connectivity."""
    results: dict[str, str] = {}

    # PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        results["postgres"] = "ok"
    except Exception as exc:
        logger.error("Postgres health check failed: %s", exc)
        results["postgres"] = "error"

    # Redis
    try:
        await get_redis().ping()
        results["redis"] = "ok"
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        results["redis"] = "error"

    # Inode check
    try:
        proc = await asyncio.create_subprocess_exec(
            "df",
            # No `-i`: GNU df rejects it together with --output, and ipcent
            # already selects the inode column.
            "--output=ipcent",
            settings.data_cas_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        lines = stdout.decode().strip().split("\n")
        if len(lines) >= 2:
            pct = int(lines[1].strip().rstrip("%"))
            if pct > 90:
                results["inodes"] = f"warning: {pct}% used"
            else:
                results["inodes"] = "ok"
        else:
            logger.warning("Inode check returned no data: %s", stderr.decode(errors="replace").strip())
            results["inodes"] = "unknown"
    except Exception as exc:
        logger.warning("Inode check failed: %s", exc)
        results["inodes"] = "unknown"

    if any(v.startswith("error") for v in results.values()):
        raise HTTPException(status_code=503, detail=results)

    return {"status": "ok", "services": results}


@router.get("/info")
async def system_info(_: dict = Depends(require_auth)):
    """Return non-sensitive runtime configuration including component versions."""
    from worker.gallery_dl_venv import get_current_version

    pg_ver, redis_ver, gdl_version = await asyncio.gather(
        _get_postgresql_version(),
        _get_redis_version(),
        get_current_version(),
    )
    jyzrox_ver = _STATIC_VERSIONS["jyzrox"]
    return {
        "version": jyzrox_ver,
        "eh_max_concurrency": settings.eh_max_concurrency,
        "versions": {
            "jyzrox": jyzrox_ver,
            "python": _STATIC_VERSIONS["python"],
            "fastapi": _STATIC_VERSIONS["fastapi"],
            "gallery_dl": gdl_version,
            "postgresql": pg_ver,
            "redis": redis_ver,
        },
    }


# Anything nested inside an excluded system directory is excluded too. Docker
# bind-mounts single files as their own mount entries, so secrets such as
# /run/secrets/novel_deploy_key surface in disk_partitions() even though /run
# itself is excluded -- and they report the whole backing filesystem's usage
# under the file's name. "/" is skipped here because every absolute path is
# nested under it; the root filesystem is labelled explicitly instead.
_MOUNT_EXCLUDE_PREFIXES: tuple[str, ...] = tuple(sorted(p.rstrip("/") + "/" for p in MOUNT_EXCLUDE_PATHS if p != "/"))


def _get_real_mounts() -> list[tuple[str, str]]:
    """Return (label, path) for all real disk mount points.

    Uses psutil.disk_partitions() and filters out virtual/system filesystems.
    """
    KNOWN_LABELS = {
        settings.data_gallery_path: "Gallery Data",
        settings.data_cas_path: "CAS (Content-Addressed)",
        "/": "Root Filesystem",
    }

    result: list[tuple[str, str]] = []
    seen_paths: set[str] = set()

    # Always include known data paths (they may share a mount with /data). Data
    # paths come first so they win the caller's per-device deduplication when a
    # deployment keeps everything on one disk.
    for path, label in KNOWN_LABELS.items():
        result.append((label, path))
        seen_paths.add(path)

    for p in psutil.disk_partitions(all=True):
        if p.fstype in MOUNT_EXCLUDE_FS:
            continue
        if p.mountpoint in MOUNT_EXCLUDE_PATHS:
            continue
        if p.mountpoint.startswith(_MOUNT_EXCLUDE_PREFIXES):
            continue
        if p.mountpoint in seen_paths:
            continue
        label = KNOWN_LABELS.get(p.mountpoint, p.mountpoint.rstrip("/").rsplit("/", 1)[-1] or p.mountpoint)
        result.append((label, p.mountpoint))
        seen_paths.add(p.mountpoint)

    return result


@router.get("/storage")
async def system_storage(_: dict = Depends(_admin)):
    """Return disk usage for configured data paths and detected mounts."""
    mount_list = await asyncio.to_thread(_get_real_mounts)

    # Gather all stat results in parallel
    stat_results = await asyncio.gather(
        *(asyncio.to_thread(os.stat, path) for _, path in mount_list),
        return_exceptions=True,
    )

    # Deduplicate by device ID, then gather disk_usage in parallel
    seen_devs: set[int] = set()
    usage_tasks: list = []
    valid_mounts: list[tuple[str, str]] = []
    for (label, path), stat in zip(mount_list, stat_results, strict=False):
        if isinstance(stat, BaseException):
            continue
        if stat.st_dev in seen_devs:
            continue
        seen_devs.add(stat.st_dev)
        usage_tasks.append(asyncio.to_thread(shutil.disk_usage, path))
        valid_mounts.append((label, path))

    usage_results = await asyncio.gather(*usage_tasks, return_exceptions=True)

    # A second pass on the reported capacity: st_dev separates superblocks, but
    # a container's overlay "/" and a bind mount from the host both report the
    # backing filesystem's usage under different device IDs. Identical
    # total+free means the same storage, so keep only the first (better
    # labelled) one.
    mounts = []
    seen_usage: set[tuple[int, int]] = set()
    for (label, path), usage in zip(valid_mounts, usage_results, strict=False):
        if isinstance(usage, BaseException):
            continue
        if (usage.total, usage.free) in seen_usage:
            continue
        seen_usage.add((usage.total, usage.free))
        percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
        mounts.append(
            {
                "label": label,
                "path": path,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": percent,
            }
        )
    return {"mounts": mounts}


router.include_router(system_cache.router)
router.include_router(system_ops.router)
