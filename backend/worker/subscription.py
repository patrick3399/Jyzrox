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
    from core.redis_client import get_redis, publish_job_event

    pool = ctx.get("redis")
    if not pool:
        return {"status": "failed", "error": "no redis pool"}

    # Race-condition guard: use Redis SETNX so only one concurrent check per sub proceeds
    redis = get_redis()
    lock_key = f"subscription:check_lock:{sub.id}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=60)
    if not acquired:
        logger.info("[subscription] sub=%d check already in progress, skipping", sub.id)
        return {"status": "skipped", "reason": "check_in_progress"}

    # Source-enabled check
    source = sub.source or "gallery_dl"
    try:
        from routers.download import _check_source_enabled
        await _check_source_enabled(source)
    except Exception:
        logger.warning("[subscription] sub=%d source '%s' disabled, skipping", sub.id, source)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription).where(Subscription.id == sub.id).values(
                    last_status="failed",
                    last_error=f"Download source '{source}' is disabled",
                )
            )
            await session.commit()
        return {"status": "skipped", "reason": "source_disabled"}

    # Credential check — skip if required credentials are missing
    from plugins.builtin.gallery_dl._sites import get_site_config
    cfg = get_site_config(source)
    if cfg.credential_requirement == "required":
        from services.credential import get_credential
        cred = await get_credential(cfg.source_id)
        if not cred:
            logger.warning("[subscription] sub=%d source '%s' requires credentials, skipping", sub.id, source)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription).where(Subscription.id == sub.id).values(
                        last_status="failed",
                        last_error=f"{cfg.name} credentials not configured",
                    )
                )
                await session.commit()
            return {"status": "skipped", "reason": "credentials_required"}

    # Duplicate guard: skip if there's already ANY queued/running job for this URL (cross-entry protection)
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(DownloadJob.id).where(
                DownloadJob.url == sub.url,
                DownloadJob.status.in_(["queued", "running"]),
            ).limit(1)
        )).scalar_one_or_none()
        if existing:
            logger.info("[subscription] sub=%d URL already has active job %s, skipping", sub.id, existing)
            return {"status": "skipped", "reason": "active_job_exists"}

    # Decide archive behavior: query galleries table (stable, not cleared by clear_finished_jobs).
    # If a gallery with matching source_url exists and is complete/partial, use archive for incremental download.
    skip_archive = True
    async with AsyncSessionLocal() as session:
        from db.models import Gallery
        existing_gallery = (await session.execute(
            select(Gallery.id).where(
                Gallery.source_url == sub.url,
                Gallery.download_status.in_(["complete", "partial"]),
            ).limit(1)
        )).scalar_one_or_none()
        if existing_gallery:
            skip_archive = False

    options = {"skip_archive": True} if skip_archive else None

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
        options, str(job_id), None,
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
