"""Subscription group scheduler and group check jobs."""

import asyncio
from datetime import UTC, datetime

from croniter import croniter as _croniter_cls
from sqlalchemy import select, update

from core.database import AsyncSessionLocal
from db.models import Subscription, SubscriptionGroup
from worker.constants import logger
import core.queue

GROUP_MAX_DURATION = 1800  # 30 minutes


def _cron_is_due(schedule: str, last_run: datetime | None) -> bool:
    """Check if a cron schedule is due based on last run time."""
    base = last_run or datetime(2000, 1, 1, tzinfo=UTC)
    it = _croniter_cls(schedule, base)
    next_run = it.get_next(datetime)
    return datetime.now(UTC) >= next_run


async def subscription_scheduler(ctx: dict) -> dict:
    """1-minute cron: dispatch due subscription groups.

    Queries groups that are enabled and idle, checks if their cron schedule
    is due, and enqueues check_subscription_group jobs for each.
    """
    pool = ctx.get("redis")
    if not pool:
        return {"status": "failed", "error": "no redis pool"}

    dispatched = 0
    async with AsyncSessionLocal() as session:
        groups = (
            (
                await session.execute(
                    select(SubscriptionGroup)
                    .where(
                        SubscriptionGroup.enabled.is_(True),
                        SubscriptionGroup.status == "idle",
                    )
                    .order_by(SubscriptionGroup.priority.desc())
                )
            )
            .scalars()
            .all()
        )

        for group in groups:
            last = group.last_completed_at or group.last_run_at
            if not _cron_is_due(group.schedule, last):
                continue

            # Atomic claim: only proceed if still idle
            result = await session.execute(
                update(SubscriptionGroup)
                .where(
                    SubscriptionGroup.id == group.id,
                    SubscriptionGroup.status == "idle",
                )
                .values(status="running", last_run_at=datetime.now(UTC))
                .returning(SubscriptionGroup.id)
            )
            claimed = result.fetchone()
            await session.commit()

            if not claimed:
                continue

            # Enqueue the group check job
            try:
                await core.queue.enqueue("check_subscription_group", group_id=group.id)
                dispatched += 1
                logger.info("[scheduler] Dispatched group %d (%s)", group.id, group.name)
            except Exception as exc:
                logger.error("[scheduler] Failed to enqueue group %d: %s", group.id, exc)
                # Reset status on failure
                await session.execute(
                    update(SubscriptionGroup).where(SubscriptionGroup.id == group.id).values(status="idle")
                )
                await session.commit()

    return {"status": "ok", "dispatched": dispatched}


async def check_subscription_group(ctx: dict, group_id: int) -> dict:
    """Check all subscriptions in a group with concurrency control."""
    from worker.subscription import _enqueue_for_subscription

    async with AsyncSessionLocal() as session:
        group = await session.get(SubscriptionGroup, group_id)
        if not group:
            logger.error("[group_check] Group %d not found", group_id)
            return {"status": "failed", "error": "group not found"}

        if group.status == "paused":
            logger.info("[group_check] Group %d is paused, skipping", group_id)
            return {"status": "skipped", "reason": "paused"}

        group_name = group.name
        concurrency = group.concurrency or 2

        # Load eligible subscriptions in same session
        subs = (
            (
                await session.execute(
                    select(Subscription).where(
                        Subscription.group_id == group_id,
                        Subscription.enabled.is_(True),
                        Subscription.auto_download.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

    if not subs:
        logger.info("[group_check] Group %d (%s) has no eligible subs", group_id, group_name)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SubscriptionGroup)
                .where(SubscriptionGroup.id == group_id)
                .values(status="idle", last_completed_at=datetime.now(UTC))
            )
            await session.commit()
        return {"status": "ok", "checked": 0, "enqueued": 0}

    checked = 0
    enqueued = 0
    errors = 0
    skipped_timeout = 0
    sem = asyncio.Semaphore(concurrency)
    deadline = datetime.now(UTC).timestamp() + GROUP_MAX_DURATION

    async def _check_one(sub):
        nonlocal checked, enqueued, errors, skipped_timeout
        # Compute remaining time for EACH coroutine (spec: timeout wraps sem + work)
        remaining = deadline - datetime.now(UTC).timestamp()
        if remaining <= 0:
            skipped_timeout += 1
            return
        try:
            async with asyncio.timeout(remaining):
                async with sem:
                    checked += 1
                    result = await _enqueue_for_subscription(ctx, sub)
                    if result.get("status") == "ok":
                        enqueued += 1
        except TimeoutError:
            skipped_timeout += 1
        except Exception as exc:
            errors += 1
            logger.error("[group_check] Error for sub %d in group %d: %s", sub.id, group_id, exc)

    try:
        # Run all subscriptions with concurrency control
        await asyncio.gather(
            *[_check_one(sub) for sub in subs],
            return_exceptions=True,
        )

        if skipped_timeout:
            logger.warning(
                "[group_check] Group %d timed out after %ds, skipped %d/%d subs",
                group_id,
                GROUP_MAX_DURATION,
                skipped_timeout,
                len(subs),
            )
    except Exception:
        # On unexpected error, ensure group is reset to idle
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SubscriptionGroup).where(SubscriptionGroup.id == group_id).values(status="idle")
            )
            await session.commit()
        raise

    # Mark group as complete
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(SubscriptionGroup)
            .where(SubscriptionGroup.id == group_id)
            .values(status="idle", last_completed_at=datetime.now(UTC))
        )
        await session.commit()

    # Emit completion event
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_GROUP_COMPLETED,
        resource_type="subscription_group",
        resource_id=group_id,
        checked=checked,
        enqueued=enqueued,
        errors=errors,
    )

    logger.info(
        "[group_check] Group %d (%s) done: checked=%d enqueued=%d errors=%d skipped=%d",
        group_id,
        group_name,
        checked,
        enqueued,
        errors,
        skipped_timeout,
    )
    return {"status": "ok", "checked": checked, "enqueued": enqueued, "errors": errors}
