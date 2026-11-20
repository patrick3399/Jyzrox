"""Subscription/followed artist jobs for the worker package."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, update

from core.database import AsyncSessionLocal
from db.models import Subscription
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run
from worker.subscription_enqueue import _enqueue_for_subscription


async def check_single_subscription(ctx: dict, sub_id: int, force_full_scan: bool = False) -> dict:
    """Check a single subscription — enqueue a download job for it.

    force_full_scan: if True, run as Force re-scan (no date-after, no archive).
    """
    from core.redis_client import publish_job_event

    async with AsyncSessionLocal() as session:
        sub = await session.get(Subscription, sub_id)
        if not sub:
            await publish_job_event(
                {
                    "type": "subscription_checked",
                    "sub_id": sub_id,
                    "status": "failed",
                    "job_id": None,
                    "user_id": None,
                }
            )
            return {"status": "failed", "error": "subscription not found"}

    try:
        return await _enqueue_for_subscription(ctx, sub, force_full_scan=force_full_scan, manual=True)
    except Exception as exc:
        logger.error("[subscription] error processing sub %d: %s", sub_id, exc)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == sub_id)
                .values(
                    last_checked_at=datetime.now(UTC),
                    last_status="failed",
                    last_error=str(exc)[:500],
                )
            )
            await session.commit()
        await publish_job_event(
            {
                "type": "subscription_checked",
                "sub_id": sub_id,
                "status": "failed",
                "job_id": None,
                "user_id": None,
            }
        )
        return {"status": "failed", "error": str(exc)}


async def check_followed_artists(ctx: dict, user_id: int | None = None) -> dict:
    """Check all enabled subscriptions and enqueue download jobs."""
    if user_id is None:
        if not await _cron_should_run(ctx, "check_subscriptions", "30 */2 * * *"):
            logger.info("[check_followed] Skipping — cron gate not reached")
            return {"status": "skipped"}
        await _cron_record(ctx, "check_subscriptions", "running")

    total_checked = 0
    total_enqueued = 0

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        query = select(Subscription).where(Subscription.enabled.is_(True))
        if user_id:
            query = query.where(Subscription.user_id == user_id)
        else:
            # Only check ungrouped subscriptions whose next_check_at is due
            # (group-assigned subs are handled by subscription_scheduler)
            from sqlalchemy import or_

            query = query.where(
                Subscription.auto_download.is_(True),
                Subscription.group_id.is_(None),
                or_(
                    Subscription.next_check_at.is_(None),
                    Subscription.next_check_at <= now,
                ),
            )
        subs = (await session.execute(query)).scalars().all()

    from worker.subscription_group import _spacing_delay

    for sub in subs:
        try:
            result = await _enqueue_for_subscription(ctx, sub)
            total_checked += 1
            if result.get("status") == "ok":
                total_enqueued += 1
            # Randomized spacing (anti-bot pacing; was a fixed 2s)
            await asyncio.sleep(_spacing_delay())
        except Exception as exc:
            logger.error("[check_followed] error for sub %d (%s): %s", sub.id, sub.name, exc)
            continue

    logger.info("[check_followed] done: checked=%d enqueued=%d", total_checked, total_enqueued)
    if user_id is None:
        await _cron_record(ctx, "check_subscriptions", "ok")
    return {"status": "ok", "checked": total_checked, "enqueued": total_enqueued}
