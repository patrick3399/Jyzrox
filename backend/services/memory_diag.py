"""Shared memory diagnostics: cgroup/host readings + DEBUG history recording.

Used by both the worker (memory_monitor_job cron, worker/memory.py trim hooks)
and the api (services/memory_watch.py self-sampling, STAB-011). Lives in
services/ so the api process can import it without pulling in the worker
package (importing ``worker.memory`` executes ``worker/__init__.py`` and drags
every job module into the api process).
"""

import logging
from typing import NamedTuple

logger = logging.getLogger("services.memory_diag")

_CGROUP_MEMORY_CURRENT = "/sys/fs/cgroup/memory.current"
_CGROUP_MEMORY_MAX = "/sys/fs/cgroup/memory.max"
_CGROUP_MEMORY_STAT = "/sys/fs/cgroup/memory.stat"
_CGROUP_MEMORY_PEAK = "/sys/fs/cgroup/memory.peak"
_CGROUP_MEMORY_EVENTS = "/sys/fs/cgroup/memory.events"


class ContainerMemory(NamedTuple):
    """A cgroup v2 memory reading, split by what can actually reach the limit.

    ``current`` counts reclaimable page cache, so a job streaming image files
    drives it to the limit without being anywhere near an OOM kill. ``anon`` is
    the unreclaimable part and is what the kernel cannot free to avoid one.
    ``peak`` is the kernel's own high-water mark, so a spike between two samples
    is still visible afterwards — periodic sampling can never catch one.
    """

    current: int
    anon: int
    peak: int | None
    limit: int


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


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:  # absent (older kernel) / unreadable / non-numeric
        return None


def _read_stat_anon(path: str) -> int | None:
    """Return ``anon`` bytes from ``memory.stat``, or ``None`` if unavailable."""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("anon "):
                    return int(line.split()[1])
    except Exception:
        return None
    return None


def read_container_oom_kills(path: str = _CGROUP_MEMORY_EVENTS) -> int | None:
    """Return the cgroup's cumulative ``oom_kill`` count, or ``None`` if absent.

    This is the only kill record that needs no sampling luck: the kernel
    maintains it, so a kill between two monitor ticks is still visible
    afterwards. It covers exactly the kills the container *survives* — a decode
    thread or child process killed under the limit increments it while pid 1
    keeps running, which no level reading (``anon``, ``peak``) can reveal
    because the memory is freed by the kill itself.

    It cannot see a kill that takes pid 1 down: the restart gives the container
    a fresh cgroup and the counter comes back at 0. ``worker.liveness`` covers
    that half.
    """
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except Exception:  # absent (non-Linux / cgroup v1) / unreadable
        return None
    return None


def read_container_memory_detail(
    current_path: str = _CGROUP_MEMORY_CURRENT,
    max_path: str = _CGROUP_MEMORY_MAX,
    stat_path: str = _CGROUP_MEMORY_STAT,
    peak_path: str = _CGROUP_MEMORY_PEAK,
) -> ContainerMemory | None:
    """Return a split cgroup v2 reading, or ``None`` when no limit applies.

    ``None`` means the cgroup files are unreadable (non-Linux / cgroup v1) or
    ``memory.max`` is ``"max"``, where a percentage would be meaningless.

    When ``memory.stat`` cannot be read, ``anon`` falls back to ``current``:
    without the split the pessimistic figure is the safe one, and that is the
    behaviour this module had before the split existed.
    """
    current = _read_int(current_path)
    if current is None:
        return None
    try:
        with open(max_path) as f:
            raw = f.read().strip()
    except Exception:
        return None
    if raw == "max":
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit <= 0:
        return None

    anon = _read_stat_anon(stat_path)
    return ContainerMemory(
        current=current,
        anon=current if anon is None else anon,
        peak=_read_int(peak_path),
        limit=limit,
    )


def read_container_memory(
    current_path: str = _CGROUP_MEMORY_CURRENT,
    max_path: str = _CGROUP_MEMORY_MAX,
) -> tuple[int, int] | None:
    """Return ``(current_bytes, limit_bytes)`` from cgroup v2.

    Kept for callers that only need the raw pair. Anything deciding whether
    memory pressure is real should use :func:`read_container_memory_detail`
    instead — ``current`` includes reclaimable page cache.
    """
    detail = read_container_memory_detail(current_path=current_path, max_path=max_path)
    return None if detail is None else (detail.current, detail.limit)


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
