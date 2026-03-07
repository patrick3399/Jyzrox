import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

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
async def system_info():
    """Return non-sensitive runtime configuration."""
    return {
        "version": "2.0.0",
        "eh_max_concurrency": settings.eh_max_concurrency,
        "tag_model_enabled": settings.tag_model_enabled,
    }
