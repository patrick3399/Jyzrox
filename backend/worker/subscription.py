"""Subscription/followed artist jobs for the worker package."""

import asyncio
import uuid
from datetime import UTC, datetime

from croniter import croniter as _croniter_cls
from sqlalchemy import select, update

from core.database import AsyncSessionLocal
from db.models import DownloadJob, Subscription
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run


async def _enqueue_for_subscription(ctx: dict, sub) -> dict:
    """Create a download job for a subscription and enqueue it."""
    from core.redis_client import publish_job_event

    pool = ctx.get("redis")
    if not pool:
        return {"status": "failed", "error": "no redis pool"}

    # Duplicate guard: skip if there's already a queued/running job for this sub
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(DownloadJob.id).where(
                DownloadJob.subscription_id == sub.id,
                DownloadJob.status.in_(["queued", "running"]),
            ).limit(1)
        )).scalar_one_or_none()
        if existing:
            logger.info("[subscription] sub=%d already has active job %s, skipping", sub.id, existing)
            return {"status": "skipped", "reason": "active_job_exists"}

    # Create download job
    job_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(DownloadJob(
            id=job_id,
            url=sub.url,
            source=sub.source or "gallery_dl",
            status="queued",
            progress={},
            user_id=sub.user_id,
            subscription_id=sub.id,
        ))
        await session.commit()

    # Enqueue ARQ job
    await pool.enqueue_job(
        "download_job", sub.url, sub.source or "gallery_dl",
        None, str(job_id), None,
        _job_id=str(job_id),
    )

    # Update subscription
    now = datetime.now(UTC)
    next_check = _croniter_cls(sub.cron_expr or "0 */2 * * *", now).get_next(datetime)
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Subscription).where(Subscription.id == sub.id).values(
                last_checked_at=now,
                last_job_id=job_id,
                last_status="ok",
                last_error=None,
                next_check_at=next_check,
            )
        )
        await session.commit()

    # WS event
    await publish_job_event({
        "type": "subscription_checked",
        "sub_id": sub.id,
        "status": "ok",
        "job_id": str(job_id),
        "user_id": sub.user_id,
    })

    return {"status": "ok", "job_id": str(job_id)}


async def check_single_subscription(ctx: dict, sub_id: int) -> dict:
    """Check a single subscription — enqueue a download job for it."""
    from core.redis_client import publish_job_event

    async with AsyncSessionLocal() as session:
        sub = await session.get(Subscription, sub_id)
        if not sub:
            await publish_job_event({
                "type": "subscription_checked",
                "sub_id": sub_id,
                "status": "failed",
                "job_id": None,
                "user_id": None,
            })
            return {"status": "failed", "error": "subscription not found"}

    try:
        return await _enqueue_for_subscription(ctx, sub)
    except Exception as exc:
        logger.error("[subscription] error processing sub %d: %s", sub_id, exc)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription).where(Subscription.id == sub_id).values(
                    last_checked_at=datetime.now(UTC),
                    last_status="failed",
                    last_error=str(exc)[:500],
                )
            )
            await session.commit()
        await publish_job_event({
            "type": "subscription_checked",
            "sub_id": sub_id,
            "status": "failed",
            "job_id": None,
            "user_id": None,
        })
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

    async with AsyncSessionLocal() as session:
        query = select(Subscription).where(Subscription.enabled == True)
        if user_id:
            query = query.where(Subscription.user_id == user_id)
        subs = (await session.execute(query)).scalars().all()

    for sub in subs:
        try:
            result = await _enqueue_for_subscription(ctx, sub)
            total_checked += 1
            if result.get("status") == "ok":
                total_enqueued += 1
            await asyncio.sleep(2)
        except Exception as exc:
            logger.error("[check_followed] error for sub %d (%s): %s", sub.id, sub.name, exc)
            continue

    logger.info("[check_followed] done: checked=%d enqueued=%d", total_checked, total_enqueued)
    if user_id is None:
        await _cron_record(ctx, "check_subscriptions", "ok")
    return {"status": "ok", "checked": total_checked, "enqueued": total_enqueued}
