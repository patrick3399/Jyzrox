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

# Shared diagnostics live in services/memory_diag.py so the api process can use
# them too (STAB-011); re-exported here to keep the worker-facing module (and
# the documented MEMORY_HISTORY_ENABLED debug switch usage) stable.
from services.memory_diag import (  # noqa: F401
    MEMORY_HISTORY_ENABLED,
    MEMORY_HISTORY_RETENTION_DAYS,
    ContainerMemory,
    persist_memory_history,
    read_container_memory,
    read_container_memory_detail,
    read_host_memory,
)

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

_libc = None
_libc_loaded = False


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
