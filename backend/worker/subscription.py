"""Subscription/followed artist jobs for the worker package."""

import asyncio
import uuid
from datetime import UTC, datetime

from croniter import croniter as _croniter_cls
from sqlalchemy import update
from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import DownloadJob, Subscription
from services.credential import get_credential
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run


async def _batch_enqueue(
    pool,
    sub_id: int,
    sub_name: str | None,
    user_id: int,
    source: str,
    works: list,
) -> dict:
    """Throttled batch enqueue with Redis progress tracking and WS events."""
    from core.redis_client import get_redis, publish_job_event

    redis = get_redis()

    # Read settings from Redis
    delay_raw = await redis.get("setting:subscription_enqueue_delay_ms")
    delay_ms = int(delay_raw) if delay_raw else 500
    delay_s = max(delay_ms, 100) / 1000.0

    batch_max_raw = await redis.get("setting:subscription_batch_max")
    batch_max = int(batch_max_raw) if batch_max_raw else 0

    if batch_max > 0 and len(works) > batch_max:
        works = works[:batch_max]

    total = len(works)
    enqueued = 0
    failed = 0
    started_at = datetime.now(UTC).isoformat()

    # Redis hash for real-time progress
    hash_key = f"subscription:batch:{sub_id}"
    await redis.hset(hash_key, mapping={
        "total": str(total),
        "enqueued": "0",
        "failed": "0",
        "started_at": started_at,
    })
    await redis.expire(hash_key, 86400)  # 24h TTL

    # DB: set batch_total
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Subscription).where(Subscription.id == sub_id).values(
                batch_total=total, batch_enqueued=0,
            )
        )
        await session.commit()

    # Initial WS event
    await publish_job_event({
        "type": "subscription_batch",
        "sub_id": sub_id,
        "sub_name": sub_name,
        "total": total,
        "enqueued": 0,
        "failed": 0,
        "phase": "enqueuing",
        "user_id": user_id,
    })

    for i, work in enumerate(works):
        try:
            job_id = uuid.uuid4()
            async with AsyncSessionLocal() as db_session:
                db_session.add(DownloadJob(
                    id=job_id, url=work.url,
                    source=source, status="queued", progress={},
                    user_id=user_id,
                ))
                await db_session.commit()
            await pool.enqueue_job(
                "download_job", work.url, source,
                None, str(job_id), None,
                _job_id=str(job_id),
            )
            enqueued += 1
        except Exception as exc:
            failed += 1
            logger.warning("[batch_enqueue] sub=%d failed to enqueue %s: %s", sub_id, work.url, exc)

        # Update Redis hash every item
        await redis.hset(hash_key, mapping={"enqueued": str(enqueued), "failed": str(failed)})

        # Update DB every 10 items or on last item
        if (i + 1) % 10 == 0 or i == total - 1:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription).where(Subscription.id == sub_id).values(
                        batch_enqueued=enqueued,
                    )
                )
                await session.commit()

        # WS event every 5 items or on last item
        if (i + 1) % 5 == 0 or i == total - 1:
            await publish_job_event({
                "type": "subscription_batch",
                "sub_id": sub_id,
                "sub_name": sub_name,
                "total": total,
                "enqueued": enqueued,
                "failed": failed,
                "phase": "enqueuing" if i < total - 1 else "done",
                "user_id": user_id,
            })

        # Throttle — don't sleep after last item
        if i < total - 1:
            await asyncio.sleep(delay_s)

    logger.info("[batch_enqueue] sub=%d done: total=%d enqueued=%d failed=%d", sub_id, total, enqueued, failed)
    return {"enqueued": enqueued, "failed": failed, "total": total}


async def check_followed_artists(ctx: dict, user_id: int | None = None) -> dict:
    """Check all subscribable sources for new works and optionally enqueue downloads."""
    from plugins.registry import plugin_registry

    # When called as a cron job (no explicit user_id), apply cron gating.
    if user_id is None:
        if not await _cron_should_run(ctx, "check_subscriptions", "30 */2 * * *"):
            logger.info("[check_followed] Skipping — cron gate not reached")
            return {"status": "skipped"}
        await _cron_record(ctx, "check_subscriptions", "running")

    total_checked = 0
    total_new = 0
    pool = ctx.get("redis")

    for source_name in plugin_registry.list_subscribable():
        subscribable = plugin_registry.get_subscribable(source_name)
        if not subscribable:
            continue

        credentials = await get_credential(source_name)
        if not credentials:
            logger.info("[check_followed] no %s credentials — proceeding without auth", source_name)

        async with AsyncSessionLocal() as session:
            query = select(Subscription).where(Subscription.source == source_name)
            if user_id:
                query = query.where(Subscription.user_id == user_id)
            subs = (await session.execute(query)).scalars().all()

        for sub in subs:
            try:
                new_works = await subscribable.check_new_works(
                    sub.source_id, sub.last_item_id, credentials
                )

                if new_works:
                    newest_id = new_works[0].source_id
                    updated_name = sub.name  # keep existing name

                    async with AsyncSessionLocal() as session:
                        await session.execute(
                            update(Subscription).where(
                                Subscription.id == sub.id
                            ).values(
                                last_checked_at=datetime.now(UTC),
                                last_item_id=newest_id,
                                name=updated_name,
                            )
                        )
                        await session.commit()

                    # Auto-download new works if enabled (batch throttled)
                    if sub.auto_download and pool:
                        await _batch_enqueue(
                            pool, sub.id, sub.name, sub.user_id,
                            source_name, new_works,
                        )

                    total_new += len(new_works)
                else:
                    # No new works — just update the check timestamp
                    async with AsyncSessionLocal() as session:
                        await session.execute(
                            update(Subscription).where(
                                Subscription.id == sub.id
                            ).values(last_checked_at=datetime.now(UTC))
                        )
                        await session.commit()

                total_checked += 1
                await asyncio.sleep(2)  # Rate limit between checks

            except Exception as exc:
                logger.error(
                    "[check_followed] error checking %s/%s (%s): %s",
                    source_name, sub.source_id, sub.name, exc,
                )
                continue

    logger.info("[check_followed] done: checked=%d new_works=%d", total_checked, total_new)
    if user_id is None:
        await _cron_record(ctx, "check_subscriptions", "ok")
    return {"status": "ok", "checked": total_checked, "new_works": total_new}


async def check_single_subscription(ctx: dict, sub_id: int) -> dict:
    """Check a single subscription for new works."""
    from plugins.registry import plugin_registry

    async with AsyncSessionLocal() as session:
        sub = await session.get(Subscription, sub_id)
        if not sub:
            return {"status": "failed", "error": "subscription not found"}

    subscribable = plugin_registry.get_subscribable(sub.source)
    if subscribable and sub.source_id:
        cred_raw = await get_credential(sub.source)
        credentials = cred_raw  # may be None — gallery-dl can handle public pages
        if not credentials:
            logger.info("[check_sub] no %s credentials — proceeding without auth (results may be limited)", sub.source)

        new_count = 0
        try:
            new_works = await subscribable.check_new_works(
                sub.source_id, sub.last_item_id, credentials
            )
            new_count = len(new_works)

            if new_works:
                newest_id = new_works[0].source_id

                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(Subscription).where(
                            Subscription.id == sub.id
                        ).values(
                            last_checked_at=datetime.now(UTC),
                            last_item_id=newest_id,
                            last_status="ok",
                            last_error=None,
                        )
                    )
                    await session.commit()

                if sub.auto_download and new_count > 0:
                    pool = ctx.get("redis")
                    if pool:
                        await _batch_enqueue(
                            pool, sub.id, sub.name, sub.user_id,
                            sub.source, new_works,
                        )
            else:
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(Subscription).where(
                            Subscription.id == sub.id
                        ).values(
                            last_checked_at=datetime.now(UTC),
                            last_status="ok",
                            last_error=None,
                        )
                    )
                    await session.commit()

            return {"status": "ok", "new_works": new_count}

        except Exception as exc:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription).where(Subscription.id == sub.id).values(
                        last_checked_at=datetime.now(UTC),
                        last_status="failed",
                        last_error=str(exc)[:500],
                    )
                )
                await session.commit()
            return {"status": "failed", "error": str(exc)}

    else:
        # Generic: enqueue download_job for the URL
        pool = ctx.get("redis")
        if pool and sub.auto_download:
            try:
                job_id = uuid.uuid4()
                async with AsyncSessionLocal() as db_session:
                    db_session.add(DownloadJob(
                        id=job_id, url=sub.url,
                        source=sub.source or "gallery_dl", status="queued", progress={},
                        user_id=sub.user_id,
                    ))
                    await db_session.commit()
                await pool.enqueue_job(
                    "download_job", sub.url, sub.source or "gallery_dl",
                    None, str(job_id), None,
                    _job_id=str(job_id),
                )
            except Exception as exc:
                logger.warning("[check_sub] failed to enqueue generic download: %s", exc)

        async with AsyncSessionLocal() as session:
            next_check = _croniter_cls(sub.cron_expr or "0 */2 * * *", datetime.now(UTC)).get_next(datetime)
            await session.execute(
                update(Subscription).where(Subscription.id == sub.id).values(
                    last_checked_at=datetime.now(UTC),
                    last_status="ok",
                    last_error=None,
                    next_check_at=next_check,
                )
            )
            await session.commit()

        return {"status": "ok"}
