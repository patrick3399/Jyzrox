"""Shared memory diagnostics: cgroup/host readings + DEBUG history recording.

Used by both the worker (memory_monitor_job cron, worker/memory.py trim hooks)
and the api (services/memory_watch.py self-sampling, STAB-011). Lives in
services/ so the api process can import it without pulling in the worker
package (importing ``worker.memory`` executes ``worker/__init__.py`` and drags
every job module into the api process).
"""

import logging

logger = logging.getLogger("services.memory_diag")

_CGROUP_MEMORY_CURRENT = "/sys/fs/cgroup/memory.current"
_CGROUP_MEMORY_MAX = "/sys/fs/cgroup/memory.max"

# ── DEBUG memory history ─────────────────────────────────────────────────
# Hardcoded debug switch: flip to True (and redeploy api/worker) to record a
# memory sample to the DB every monitor tick, keeping only the last few days.
# Default OFF — production never touches the DB. Self-contained
# (CREATE TABLE IF NOT EXISTS); intentionally NOT part of the formal schema.
MEMORY_HISTORY_ENABLED = False
MEMORY_HISTORY_RETENTION_DAYS = 3
_MEMORY_HISTORY_TABLE = "memory_samples"


def read_host_memory(path: str = "/proc/meminfo") -> tuple[int, int] | None:
    """Return ``(used_bytes, total_bytes)`` for the host from /proc/meminfo.

    A container's /proc/meminfo reflects the host. Used = MemTotal - MemAvailable.
    Returns ``None`` if the file is unreadable or the fields are missing.
    """
    try:
        total_kb = None
        avail_kb = None
        with open(path) as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                if total_kb is not None and avail_kb is not None:
                    break
    except Exception:
        return None
    if total_kb is None or avail_kb is None or total_kb <= 0:
        return None
    return (total_kb - avail_kb) * 1024, total_kb * 1024


def read_container_memory(
    current_path: str = _CGROUP_MEMORY_CURRENT,
    max_path: str = _CGROUP_MEMORY_MAX,
) -> tuple[int, int] | None:
    """Return ``(used_bytes, limit_bytes)`` from cgroup v2.

    Returns ``None`` if the cgroup files are unreadable (non-Linux / cgroup v1)
    or when no memory limit is set (``memory.max`` == ``"max"``), where a
    percentage would be meaningless.
    """
    try:
        with open(current_path) as f:
            used = int(f.read().strip())
        with open(max_path) as f:
            raw = f.read().strip()
    except Exception:  # cgroup unreadable / non-numeric → no usable figure
        return None
    if raw == "max":
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit <= 0:
        return None
    return used, limit


async def persist_memory_history(samples: list[tuple[str, float, float, float]]) -> None:
    """Append memory samples to the self-managed DEBUG table and prune old rows.

    ``samples`` is a list of ``(source, used_mb, limit_mb, pct)``. The table and
    its index are created on demand so this leaves no trace when the debug switch
    is off. Pruning keeps only ``MEMORY_HISTORY_RETENTION_DAYS`` of history.
    """
    from sqlalchemy import text

    from core.database import async_session

    async with async_session() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {_MEMORY_HISTORY_TABLE} ("
                "id BIGSERIAL PRIMARY KEY, "
                "ts TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "source TEXT NOT NULL, "
                "used_mb DOUBLE PRECISION, "
                "limit_mb DOUBLE PRECISION, "
                "pct DOUBLE PRECISION)"
            )
        )
        await session.execute(
            text(f"CREATE INDEX IF NOT EXISTS ix_{_MEMORY_HISTORY_TABLE}_ts ON {_MEMORY_HISTORY_TABLE} (ts)")
        )
        for source, used_mb, limit_mb, pct in samples:
            await session.execute(
                text(
                    f"INSERT INTO {_MEMORY_HISTORY_TABLE} (source, used_mb, limit_mb, pct) "
                    "VALUES (:source, :used_mb, :limit_mb, :pct)"
                ),
                {"source": source, "used_mb": used_mb, "limit_mb": limit_mb, "pct": pct},
            )
        await session.execute(
            text(f"DELETE FROM {_MEMORY_HISTORY_TABLE} WHERE ts < now() - make_interval(days => :days)"),
            {"days": MEMORY_HISTORY_RETENTION_DAYS},
        )
        await session.commit()
