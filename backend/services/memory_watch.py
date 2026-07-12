"""Periodic self-sampling of api process memory (STAB-011).

The api container's memory floor creeps up across weeks (~120 MB fresh to
~280+ MB daily minimum) and only a restart reclaims it. The worker container
already has cron-based cgroup monitoring (``memory_monitor_job``), but the api
processes were blind: the creep lives in the uvicorn worker processes' RSS,
and reading a sibling process's /proc is blocked by the container's seccomp
profile — each process has to sample itself.

Each api process runs one watch task (``uvicorn --workers N`` => N tasks,
labelled by pid). Every ``settings.memory_watch_interval_sec`` the task:

- logs its own RSS plus the container cgroup figure, so RSS-over-uptime can be
  read straight from the api logs;
- appends a per-pid row to the DEBUG history table when
  ``services.memory_diag.MEMORY_HISTORY_ENABLED`` is flipped on (same switch
  the worker uses);
- with ``API_TRACEMALLOC=1``, logs the top Python allocation sites each tick
  so a genuine reference leak can be located without attaching a debugger.
  tracemalloc costs extra memory and CPU — diagnosis only, never a default.

The cgroup-threshold alert mirrors worker ``memory_monitor_job`` semantics
(SYSTEM_MEMORY_HIGH event + warning log). With multiple api processes the
alert can fire once per process per tick; acceptable for a diagnosis tool.
"""

import asyncio
import logging
import os
import tracemalloc

from core.config import settings
from services import memory_diag

logger = logging.getLogger("api.memory_watch")

_TRACEMALLOC_FRAMES = 15
_TRACEMALLOC_TOP = 8


def read_self_rss(status_path: str = "/proc/self/status") -> int | None:
    """Return this process's resident set size in bytes from /proc.

    Returns ``None`` when the file is unreadable or has no VmRSS line
    (non-Linux dev machines).
    """
    try:
        with open(status_path) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _log_top_allocations() -> None:
    snapshot = tracemalloc.take_snapshot()
    for stat in snapshot.statistics("lineno")[:_TRACEMALLOC_TOP]:
        logger.info("[memory_watch] tracemalloc %s", stat)


async def sample_once() -> dict:
    """One sampling tick: log RSS + cgroup, alert on threshold, record history."""
    pid = os.getpid()
    rss = read_self_rss()
    rss_mb = round(rss / (1024 * 1024), 1) if rss is not None else None

    mem = memory_diag.read_container_memory()
    if mem is None:
        logger.info("[memory_watch] pid=%d rss=%sMB (no cgroup limit)", pid, rss_mb)
        return {"status": "ok", "pid": pid, "rss_mb": rss_mb}

    used_bytes, limit_bytes = mem
    used_mb = round(used_bytes / (1024 * 1024), 1)
    limit_mb = round(limit_bytes / (1024 * 1024), 1)
    pct = round(used_bytes / limit_bytes * 100, 1)
    logger.info(
        "[memory_watch] pid=%d rss=%sMB cgroup=%.1f/%.0fMB (%.1f%%)",
        pid,
        rss_mb,
        used_mb,
        limit_mb,
        pct,
    )

    if tracemalloc.is_tracing():
        _log_top_allocations()

    if memory_diag.MEMORY_HISTORY_ENABLED and rss is not None and rss_mb is not None:
        rss_pct = round(rss / limit_bytes * 100, 1)
        await memory_diag.persist_memory_history([(f"api:{pid}", rss_mb, limit_mb, rss_pct)])

    threshold = settings.memory_alert_pct
    if pct >= threshold:
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.SYSTEM_MEMORY_HIGH,
            resource_type="system",
            component="api",
            used_mb=used_mb,
            limit_mb=limit_mb,
            pct=pct,
            threshold_pct=threshold,
        )
        logger.warning(
            "[memory_watch] HIGH: %.0f MB / %.0f MB (%.1f%%, threshold %.0f%%)",
            used_mb,
            limit_mb,
            pct,
            threshold,
        )
        return {"status": "high", "pid": pid, "rss_mb": rss_mb, "pct": pct}

    return {"status": "ok", "pid": pid, "rss_mb": rss_mb, "pct": pct}


async def memory_watch_loop() -> None:
    """Sample immediately (startup baseline), then every configured interval."""
    if settings.api_tracemalloc and not tracemalloc.is_tracing():
        tracemalloc.start(_TRACEMALLOC_FRAMES)
        logger.info("[memory_watch] tracemalloc enabled (%d frames)", _TRACEMALLOC_FRAMES)

    interval = max(30.0, float(settings.memory_watch_interval_sec))
    while True:
        try:
            await sample_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[memory_watch] sample failed")
        await asyncio.sleep(interval)
