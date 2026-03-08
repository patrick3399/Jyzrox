import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from core.auth import require_auth
from core.config import settings
from core.database import AsyncSessionLocal
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


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

    if any(v != "ok" for v in results.values()):
        raise HTTPException(status_code=503, detail=results)

    return {"status": "ok", "services": results}


@router.get("/info")
async def system_info(_: dict = Depends(require_auth)):
    """Return non-sensitive runtime configuration."""
    return {
        "version": "0.1",
        "eh_max_concurrency": settings.eh_max_concurrency,
        "tag_model_enabled": settings.tag_model_enabled,
    }


# ── Cache management ──────────────────────────────────────────────────

_CACHE_PATTERNS: dict[str, str] = {
    "eh_search": "eh:search:*",
    "eh_gallery": "eh:gallery:*",
    "eh_image": "thumb:proxied:*",
    "thumbs": "thumb:cdn:*",
}


async def _count_keys(pattern: str) -> int:
    """Count Redis keys matching a glob pattern (uses SCAN to avoid blocking)."""
    r = get_redis()
    count = 0
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor, match=pattern, count=200)
        count += len(keys)
        if cursor == 0:
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
async def get_cache_stats(_: dict = Depends(require_auth)):
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
async def clear_cache(_: dict = Depends(require_auth)):
    """Clear all EH cache (search, gallery, images, thumbs). Does not clear sessions."""
    deleted = 0
    for pattern in _CACHE_PATTERNS.values():
        deleted += await _delete_keys(pattern)
    # Also clear popular/toplist/comments/favorites
    for pattern in ("eh:popular", "eh:toplist:*", "eh:comments:*", "eh:favorites:*",
                     "eh:previews:*", "eh:imagelist:*"):
        deleted += await _delete_keys(pattern)
    return {"status": "ok", "deleted_keys": deleted}


@router.delete("/cache/{category}")
async def clear_cache_category(
    category: str,
    _: dict = Depends(require_auth),
):
    """Clear a specific cache category: eh_search, eh_gallery, eh_image, thumbs."""
    if category not in _CACHE_PATTERNS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category. Valid: {list(_CACHE_PATTERNS.keys())}",
        )
    deleted = await _delete_keys(_CACHE_PATTERNS[category])
    return {"status": "ok", "category": category, "deleted_keys": deleted}
