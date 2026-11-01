"""Redis memory sampling and the image-cache budget (ADR 0018).

Redis holds sessions, locks and queue state next to disposable caches and runs
`noeviction` (ADR 0006), so nothing in Redis makes room when it fills up. Proxied
image bytes are the only cache large enough to fill it, so the application bounds
them itself: the worker trims the oldest ones once usage crosses a watermark, and
writers stop admitting new ones before the control plane runs out of room.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("services.redis_memory")

# How long one admission decision is reused. Admission exists to stop a burst
# between two trims, and a burst is bounded by how fast images can be proxied:
# the busiest five minutes on record wrote 84 MB, about 3 MB per ten seconds.
ADMISSION_MEMO_SEC = 10.0

_admission_memo: tuple[float, bool] | None = None


async def sample_redis_memory(redis: Any) -> dict[str, int | float | str] | None:
    """Return Redis maxmemory usage and eviction-policy diagnostics.

    Redis holds sessions and job-control keys alongside disposable caches. The
    sample is best-effort so a monitoring failure never breaks its caller.
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


def reset_admission_memo() -> None:
    """Forget the memoized admission decision."""
    global _admission_memo
    _admission_memo = None


async def image_cache_writes_admitted(redis: Any, max_pct: float) -> bool:
    """Whether image bytes may still be written to the cache.

    The trim runs every five minutes; this is what bounds the cache in between.
    It fails open: with no reading, or no maxmemory to measure against, refusing
    the write protects nothing, and the write itself is already best-effort.
    """
    global _admission_memo
    now = time.monotonic()
    if _admission_memo is not None and now < _admission_memo[0]:
        return _admission_memo[1]

    sample = await sample_redis_memory(redis)
    admitted = True
    if sample is not None and int(sample["limit_bytes"]) > 0:
        admitted = float(sample["pct"]) < max_pct
    _admission_memo = (now + ADMISSION_MEMO_SEC, admitted)
    return admitted


async def trim_image_cache(
    redis: Any,
    ttl_by_prefix: Mapping[str, int],
    *,
    bytes_to_free: int,
    max_keys: int = 200_000,
    time_budget_sec: float = 15.0,
    batch_size: int = 500,
) -> dict[str, int | bool]:
    """Delete the oldest image-cache keys until `bytes_to_free` bytes are released.

    Only keys under `ttl_by_prefix` are considered, so sessions, locks, queue
    state and the small JSON caches can never be chosen. "Oldest" means written
    first: every key under a prefix is stored with that prefix's TTL, so its age
    is the TTL minus what remains of it. Reads do not refresh a key.

    The scan is bounded by `max_keys` and `time_budget_sec`; when either stops it
    early the result reports `truncated` and the next run carries on.
    """
    result: dict[str, int | bool] = {"scanned": 0, "deleted_keys": 0, "freed_bytes": 0, "truncated": False}
    if bytes_to_free <= 0:
        return result

    started = time.monotonic()
    # Scanning gets two thirds of the budget so it can never starve the deletes:
    # a run that only ever scans would repeat itself forever.
    scan_deadline = started + time_budget_sec * 2 / 3
    deadline = started + time_budget_sec
    entries: list[tuple[int, int, Any]] = []  # (age_sec, size_bytes, key)
    scanned = 0
    truncated = False

    for prefix, full_ttl in ttl_by_prefix.items():
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=batch_size)
            if keys:
                pipe = redis.pipeline(transaction=False)
                for key in keys:
                    pipe.ttl(key)
                    pipe.strlen(key)
                raw = await pipe.execute()
                for index, key in enumerate(keys):
                    ttl = raw[index * 2]
                    size = raw[index * 2 + 1]
                    # ttl -2: expired between SCAN and here. ttl -1: no expiry,
                    # so not something this cache wrote and nothing to rank by.
                    if ttl is None or int(ttl) < 0 or not size:
                        continue
                    entries.append((full_ttl - int(ttl), int(size), key))
                scanned += len(keys)
            if cursor == 0:
                break
            if scanned >= max_keys or time.monotonic() >= scan_deadline:
                truncated = True
                break
        if truncated:
            break

    entries.sort(key=lambda entry: entry[0], reverse=True)

    doomed: list[tuple[int, Any]] = []
    planned = 0
    for _age, size, key in entries:
        if planned >= bytes_to_free:
            break
        doomed.append((size, key))
        planned += size

    deleted = 0
    freed = 0
    for start in range(0, len(doomed), batch_size):
        if time.monotonic() >= deadline:
            truncated = True
            break
        chunk = doomed[start : start + batch_size]
        deleted += int(await redis.unlink(*(key for _size, key in chunk)))
        freed += sum(size for size, _key in chunk)

    result.update(scanned=scanned, deleted_keys=deleted, freed_bytes=freed, truncated=truncated)
    return result
