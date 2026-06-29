"""Return worker heap back to the OS after memory-heavy jobs.

Large batch jobs (dedup pHash scan, bulk import, thumbnailing) allocate and free
hundreds of MB transiently. CPython frees the Python objects but glibc keeps the
freed arenas, so the worker RSS ratchets up in step plateaus and is only reclaimed
on restart — eventually hitting the 2 GB container cap (and, before that cap
existed, exhausting the whole host). Forcing a GC sweep + ``malloc_trim`` after
heavy jobs hands that memory back to the OS so back-to-back scans don't accumulate.

Pair this with ``MALLOC_ARENA_MAX=2`` in the worker environment to cap per-thread
arena fragmentation.
"""

import ctypes
import ctypes.util
import gc
import logging

logger = logging.getLogger("worker.memory")

# Jobs known to allocate large transient buffers / load big result sets. Only
# these trigger a trim — frequent lightweight cron ticks must not pay the cost.
HEAVY_JOB_FUNCTIONS = frozenset(
    {
        "dedup_scan_job",
        "dedup_tier1_job",
        "dedup_tier2_job",
        "dedup_tier3_job",
        "import_job",
        "batch_import_job",
        "local_import_job",
        "thumbnail_job",
        "thumbhash_backfill_job",
        "rescan_library_job",
        "rescan_library_path_job",
        "scheduled_scan_job",
        "reconciliation_job",
    }
)

_CGROUP_MEMORY_CURRENT = "/sys/fs/cgroup/memory.current"
_CGROUP_MEMORY_MAX = "/sys/fs/cgroup/memory.max"

# ── DEBUG memory history ─────────────────────────────────────────────────
# Hardcoded debug switch: flip to True (and redeploy worker) to record a
# memory sample to the DB every memory_monitor cron tick, keeping only the
# last few days. Default OFF — production never touches the DB. Self-contained
# (CREATE TABLE IF NOT EXISTS); intentionally NOT part of the formal schema.
MEMORY_HISTORY_ENABLED = False
MEMORY_HISTORY_RETENTION_DAYS = 3
_MEMORY_HISTORY_TABLE = "memory_samples"

_libc = None
_libc_loaded = False


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


def _load_libc():
    """Load libc once; return None if unavailable (e.g. musl)."""
    global _libc, _libc_loaded
    if _libc_loaded:
        return _libc
    _libc_loaded = True
    try:
        name = ctypes.util.find_library("c") or "libc.so.6"
        _libc = ctypes.CDLL(name)
    except OSError:
        _libc = None
    return _libc


def _malloc_trim() -> None:
    """Ask the allocator to return free heap to the OS (glibc ``malloc_trim``)."""
    libc = _load_libc()
    if libc is None or not hasattr(libc, "malloc_trim"):
        return
    try:
        libc.malloc_trim(0)
    except Exception:  # pragma: no cover - defensive; trimming is best-effort
        pass


def trim_memory() -> None:
    """Force a GC sweep then return freed heap arenas to the OS."""
    gc.collect()
    _malloc_trim()


async def after_process_hook(ctx) -> None:
    """SAQ ``after_process`` hook: trim memory after a memory-heavy job finishes."""
    job = ctx.get("job") if isinstance(ctx, dict) else None
    function = getattr(job, "function", None)
    if function in HEAVY_JOB_FUNCTIONS:
        logger.debug("trim_memory after heavy job %s", function)
        trim_memory()
