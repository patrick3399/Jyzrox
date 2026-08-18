"""Detects a worker run that ended without ever reaching ``shutdown()``.

``services.memory_diag.read_container_oom_kills`` reports kills the container
survives. It cannot report the kind that matters most — the one that takes pid 1
down — because Docker recreates the cgroup on restart and the counter comes back
at 0. Verified 2026-08-18 against this stack: a child killed under the limit
leaves ``oom_kill 1`` behind, while a container restart resets it to 0.

So the worker leaves a marker in Redis for the duration of a run and deletes it
on clean shutdown. Finding one at startup means the previous run was killed,
crashed, or was force-stopped. The marker carries the last memory sample the
monitor recorded, which is the closest thing to a cause that survives the kill.

The polarity is deliberate: *presence* means trouble. A lost or unreadable
marker can only cost a report, never invent one — the failure mode of an alert
nobody can trust is worse than a missed line.
"""

import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

RUN_MARKER_KEY = "worker:run_marker"

# Outlives any restart gap but expires if the worker is retired for good, so a
# decommissioned marker cannot report a phantom crash months later.
_RUN_MARKER_TTL_SEC = 7 * 24 * 3600

# When this run opened. Set by ``start_run_marker`` and carried into every
# later write so the marker always says how long the run had been alive.
_started_at: str | None = None


async def detect_unclean_exit(redis) -> dict | None:
    """Return the previous run's marker if it never shut down, else ``None``.

    Consumes the marker either way, so one unclean exit is reported once.
    """
    try:
        raw = await redis.get(RUN_MARKER_KEY)
    except Exception as exc:
        logger.warning("[liveness] could not read the run marker: %s", exc)
        return None
    if raw is None:
        return None

    await clear_run_marker(redis)
    try:
        marker = json.loads(raw)
    except json.JSONDecodeError, TypeError, ValueError:
        logger.warning("[liveness] run marker was unreadable; not reporting a crash")
        return None
    return marker if isinstance(marker, dict) else None


async def start_run_marker(redis) -> None:
    """Open a run: from here until ``clear_run_marker`` a death is detectable."""
    global _started_at
    _started_at = datetime.now(UTC).isoformat()
    await _write_marker(redis, {"started_at": _started_at})


async def record_memory_sample(redis, *, anon_mb: float, pct: float) -> None:
    """Refresh the marker with the newest reading, so a kill leaves fresh evidence.

    Carries ``started_at`` forward on every write. How long the run survived is
    half the diagnostic — the 2026-08-13 worker was 120 seconds old when it was
    killed, which reads very differently from the same figure after five days —
    and a plain overwrite would drop it on the first tick. Keeping it in process
    memory rather than re-reading the marker holds this to one round trip; the
    run and the process have the same lifetime, so there is nothing to reload.
    """
    await _write_marker(
        redis,
        {
            "started_at": _started_at,
            "last_sample_at": datetime.now(UTC).isoformat(),
            "last_anon_mb": anon_mb,
            "last_pct": pct,
        },
    )


async def clear_run_marker(redis) -> None:
    """Close a run cleanly. Called from ``shutdown()``; absence means health."""
    try:
        await redis.delete(RUN_MARKER_KEY)
    except Exception as exc:
        logger.warning("[liveness] could not clear the run marker: %s", exc)


async def _write_marker(redis, payload: dict) -> None:
    try:
        await redis.set(RUN_MARKER_KEY, json.dumps(payload), ex=_RUN_MARKER_TTL_SEC)
    except Exception as exc:
        # Never let bookkeeping break a boot or a monitor tick.
        logger.warning("[liveness] could not write the run marker: %s", exc)
