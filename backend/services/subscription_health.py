"""Consecutive-failure tracking and backoff for subscriptions (Redis-backed).

Chronic failures — expired cookies, dead accounts, broken URLs — previously
failed silently on every scheduler pass: no alert, no backoff, a fresh check
every cycle forever. This module keeps a per-subscription consecutive-failure
counter in Redis, emits SUBSCRIPTION_FAILING once when the threshold is
crossed, and tells the enqueue path to skip automatic checks while inside an
exponentially growing backoff window.

Redis (not a DB column) on purpose: no schema migration, the counter
self-expires for deleted subscriptions, and losing it on Redis loss only
means one extra check cycle.
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Consecutive failures before an event is emitted and backoff kicks in.
FAILURE_ALERT_THRESHOLD = 3
# Backoff window at the threshold; doubles per further failure.
BACKOFF_BASE_S = 3600
# Backoff cap — never suppress automatic checks longer than a day.
BACKOFF_MAX_S = 86400
# Counter TTL — deleted/recovered subscriptions don't leak keys forever.
_KEY_TTL_S = 7 * 86400


def _fail_key(sub_id: int) -> str:
    return f"subscription:failcount:{sub_id}"


async def record_check_result(sub_id: int, status: str) -> int:
    """Update the consecutive-failure counter from a terminal check status.

    done/partial reset the counter; failed increments it (emitting
    SUBSCRIPTION_FAILING exactly when the threshold is crossed); anything else
    (cancelled) is a user action, not a source failure, and leaves it alone.
    Fails open: a Redis error is logged and reported as 0 failures — health
    tracking must never break the download/check flow it observes.
    Returns the current consecutive-failure count.
    """
    # Function-level import: binding get_redis at module import time would
    # freeze whichever real/mock object exists first (import-order dependent).
    from core.redis_client import get_redis

    try:
        r = get_redis()
        key = _fail_key(sub_id)

        if status in ("done", "partial"):
            await r.delete(key)
            return 0

        if status != "failed":
            raw = await r.get(key)
            return int(raw) if raw else 0

        count = int(await r.incr(key))
        await r.expire(key, _KEY_TTL_S)
    except Exception as exc:
        logger.warning("[sub_health] failure tracking unavailable for sub %d: %s", sub_id, exc)
        return 0

    if count == FAILURE_ALERT_THRESHOLD:
        from core.events import EventType, emit_safe

        logger.warning("[sub_health] subscription %d has failed %d checks in a row", sub_id, count)
        await emit_safe(
            EventType.SUBSCRIPTION_FAILING,
            resource_type="subscription",
            resource_id=sub_id,
            consecutive_failures=count,
        )
    return count


def backoff_seconds(failures: int) -> int:
    """Backoff window for the given consecutive-failure count (0 = no backoff)."""
    if failures < FAILURE_ALERT_THRESHOLD:
        return 0
    return min(BACKOFF_BASE_S * (2 ** (failures - FAILURE_ALERT_THRESHOLD)), BACKOFF_MAX_S)


async def should_backoff(sub_id: int, last_checked_at: datetime | None) -> tuple[bool, int]:
    """(skip, failures): skip is True while an automatic check should be suppressed.

    The window is measured from last_checked_at (the last enqueue attempt);
    backoff skips do not advance it, so the window cannot extend itself.
    Fails open: a Redis error means no backoff, never a blocked check.
    """
    from core.redis_client import get_redis

    try:
        r = get_redis()
        raw = await r.get(_fail_key(sub_id))
        failures = int(raw) if raw else 0
    except Exception as exc:
        logger.warning("[sub_health] backoff lookup unavailable for sub %d: %s", sub_id, exc)
        return False, 0

    window = backoff_seconds(failures)
    if window <= 0 or last_checked_at is None:
        return False, failures

    lca = last_checked_at if last_checked_at.tzinfo else last_checked_at.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - lca).total_seconds()
    return elapsed < window, failures
