import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys

import psutil

import fastapi
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from core.auth import require_auth, require_role
from core.config import settings
from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from core.utils import MOUNT_EXCLUDE_FS, MOUNT_EXCLUDE_PATHS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

_admin = require_role("admin")


# ── Static version detection (executed once at import time) ───────────

def _detect_jyzrox_version() -> str:
    """Return output of `git describe --tags --always`, fallback 'dev'."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        tag = result.stdout.strip()
        return tag if tag else "dev"
    except Exception:
        return "dev"


def _detect_gallery_dl_version() -> str | None:
    """Return gallery-dl version, or None on failure."""
    try:
        import gallery_dl  # type: ignore
        return gallery_dl.version.__version__
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["gallery-dl", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ver = result.stdout.strip()
        return ver if ver else None
    except Exception:
        return None


def _detect_python_version() -> str:
    """Return Python version string (major.minor.micro)."""
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


_STATIC_VERSIONS: dict[str, str | None] = {
    "jyzrox": _detect_jyzrox_version(),
    "python": _detect_python_version(),
    "fastapi": fastapi.__version__,
    "gallery_dl": _detect_gallery_dl_version(),
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
    """Return redis_version from INFO server."""
    try:
        info = await get_redis().info("server")
        return info.get("redis_version") or None
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
        results["postgres"] = f"error: {exc}"

    # Redis
    try:
        await get_redis().ping()
        results["redis"] = "ok"
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        results["redis"] = f"error: {exc}"

    # Inode check
    try:
        proc = await asyncio.create_subprocess_exec(
            "df", "-i", "--output=ipcent", settings.data_cas_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        lines = stdout.decode().strip().split("\n")
        if len(lines) >= 2:
            pct = int(lines[1].strip().rstrip("%"))
            if pct > 90:
                results["inodes"] = f"warning: {pct}% used"
            else:
                results["inodes"] = "ok"
        else:
            results["inodes"] = "unknown"
    except Exception:
        results["inodes"] = "unknown"

    if any(v.startswith("error") for v in results.values()):
        raise HTTPException(status_code=503, detail=results)

    return {"status": "ok", "services": results}


async def _get_tagger_info() -> dict | None:
    """Fetch tagger service health info, or None if offline."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.tagger_url}/health", timeout=5)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


@router.get("/info")
async def system_info(_: dict = Depends(require_auth)):
    """Return non-sensitive runtime configuration including component versions."""
    pg_ver, redis_ver, tagger_info = await asyncio.gather(
        _get_postgresql_version(),
        _get_redis_version(),
        _get_tagger_info(),
    )
    jyzrox_ver = _STATIC_VERSIONS["jyzrox"]
    return {
        "version": jyzrox_ver,
        "eh_max_concurrency": settings.eh_max_concurrency,
        "tag_model_enabled": settings.tag_model_enabled,
        "versions": {
            "jyzrox": jyzrox_ver,
            "python": _STATIC_VERSIONS["python"],
            "fastapi": _STATIC_VERSIONS["fastapi"],
            "gallery_dl": _STATIC_VERSIONS["gallery_dl"],
            "postgresql": pg_ver,
            "redis": redis_ver,
            "onnxruntime": tagger_info.get("onnxruntime_version") if tagger_info else None,
        },
        "tagger": tagger_info,
    }


def _get_real_mounts() -> list[tuple[str, str]]:
    """Return (label, path) for all real disk mount points.

    Uses psutil.disk_partitions() and filters out virtual/system filesystems.
    """
    KNOWN_LABELS = {
        settings.data_gallery_path: "Gallery Data",
        settings.data_cas_path: "CAS (Content-Addressed)",
    }

    result: list[tuple[str, str]] = []
    seen_paths: set[str] = set()

    # Always include known data paths (they may share a mount with /data)
    for path, label in KNOWN_LABELS.items():
        result.append((label, path))
        seen_paths.add(path)

    for p in psutil.disk_partitions(all=True):
        if p.fstype in MOUNT_EXCLUDE_FS:
            continue
        if p.mountpoint in MOUNT_EXCLUDE_PATHS:
            continue
        if p.mountpoint.startswith('/dev/'):
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
    for (label, path), stat in zip(mount_list, stat_results):
        if isinstance(stat, Exception):
            continue
        if stat.st_dev in seen_devs:
            continue
        seen_devs.add(stat.st_dev)
        usage_tasks.append(asyncio.to_thread(shutil.disk_usage, path))
        valid_mounts.append((label, path))

    usage_results = await asyncio.gather(*usage_tasks, return_exceptions=True)

    mounts = []
    for (label, path), usage in zip(valid_mounts, usage_results):
        if isinstance(usage, Exception):
            continue
        percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
        mounts.append({
            "label": label,
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": percent,
        })
    return {"mounts": mounts}


# ── Cache management ──────────────────────────────────────────────────

_CACHE_PATTERNS: dict[str, str] = {
    "eh_search": "eh:search:*",
    "eh_gallery": "eh:gallery:*",
    "eh_image": "thumb:proxied:*",
    "thumbs": "thumb:cdn:*",
    "eh_popular": "eh:popular",
    "eh_toplist": "eh:toplist:*",
    "eh_comments": "eh:comments:*",
    "eh_favorites": "eh:favorites:*",
    "eh_previews": "eh:previews:*",
    "eh_imagelist": "eh:imagelist:*",
}


async def _count_keys(pattern: str, max_iterations: int = 500) -> int:
    """Count Redis keys matching a glob pattern (uses SCAN to avoid blocking).

    Caps at max_iterations SCAN rounds (~100K keys) to prevent blocking on large keyspaces.
    """
    r = get_redis()
    count = 0
    cursor = 0
    iterations = 0
    while True:
        cursor, keys = await r.scan(cursor, match=pattern, count=200)
        count += len(keys)
        iterations += 1
        if cursor == 0 or iterations >= max_iterations:
            break
    return count


async def _delete_keys(pattern: str) -> int:
    """Delete all Redis keys matching a glob pattern via SCAN + DEL."""
    r = get_redis()
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor, match=pattern, count=200)
        if keys:
            deleted += await r.delete(*keys)
        if cursor == 0:
            break
    return deleted


@router.get("/cache")
async def get_cache_stats(_: dict = Depends(_admin)):
    """Return Redis memory usage and key counts by category."""
    r = get_redis()

    # Memory info
    info = await r.info("memory")
    used_memory = info.get("used_memory", 0)
    used_memory_human = info.get("used_memory_human", "N/A")

    # Key counts
    total_keys = await r.dbsize()
    breakdown = {}
    for category, pattern in _CACHE_PATTERNS.items():
        breakdown[category] = await _count_keys(pattern)
    breakdown["sessions"] = await _count_keys("session:*")

    return {
        "total_memory": used_memory,
        "total_memory_human": used_memory_human,
        "total_keys": total_keys,
        "breakdown": breakdown,
    }


@router.delete("/cache")
async def clear_cache(_: dict = Depends(_admin)):
    """Clear all EH cache (search, gallery, images, thumbs). Does not clear sessions."""
    deleted = 0
    for pattern in _CACHE_PATTERNS.values():
        deleted += await _delete_keys(pattern)
    return {"status": "ok", "deleted_keys": deleted}


@router.delete("/cache/{category}")
async def clear_cache_category(
    category: str,
    _: dict = Depends(_admin),
):
    """Clear a specific cache category: eh_search, eh_gallery, eh_image, thumbs."""
    if category not in _CACHE_PATTERNS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category. Valid: {list(_CACHE_PATTERNS.keys())}",
        )
    deleted = await _delete_keys(_CACHE_PATTERNS[category])
    return {"status": "ok", "category": category, "deleted_keys": deleted}


# ── Reconciliation ────────────────────────────────────────────────────


@router.post("/reconcile")
async def trigger_reconcile(
    request: Request,
    _: dict = Depends(_admin),
):
    """Manually trigger the reconciliation job via ARQ."""
    arq = request.app.state.arq
    await arq.enqueue_job("reconciliation_job")
    return {"status": "enqueued"}


@router.get("/reconcile")
async def get_reconcile_status(_: dict = Depends(require_auth)):
    """Get the result of the last reconciliation run."""
    r = get_redis()
    result = await r.get("reconcile:last_result")
    if not result:
        return {"status": "never_run"}
    return json.loads(result)


@router.get("/events")
async def get_recent_events(
    limit: int = Query(50, ge=1, le=200),
    _: dict = Depends(_admin),
):
    """Return recent system events from the EventBus. Admin only."""
    from core.events import event_bus
    events = await event_bus.get_recent(limit)
    return {"events": events, "count": len(events)}
