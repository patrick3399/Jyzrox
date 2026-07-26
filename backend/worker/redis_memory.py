"""Redis memory-pressure diagnostics for the worker monitor."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("worker.redis_memory")


async def sample_redis_memory(redis: Any) -> dict[str, int | float | str] | None:
    """Return Redis maxmemory usage and eviction-policy diagnostics.

    Redis holds sessions and job-control keys alongside disposable caches. The
    sample is best-effort so a monitoring failure never breaks the cron worker.
    """
    if redis is None:
        return None

    try:
        memory = await redis.info("memory")
        stats = await redis.info("stats")
        used_bytes = int(memory.get("used_memory", 0))
        limit_bytes = int(memory.get("maxmemory", 0))
        policy = str(memory.get("maxmemory_policy", "unknown"))
        evicted_keys = int(stats.get("evicted_keys", 0))
    except Exception as exc:  # pragma: no cover - exercised through the job
        logger.warning("Unable to sample Redis memory: %s", exc)
        return None

    pct = used_bytes / limit_bytes * 100 if limit_bytes > 0 else 0.0
    return {
        "used_bytes": used_bytes,
        "limit_bytes": limit_bytes,
        "pct": round(pct, 1),
        "policy": policy,
        "evicted_keys": evicted_keys,
    }
