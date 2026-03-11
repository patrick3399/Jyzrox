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
            logger.info("[check_followed] no %s credentials — skipping", source_name)
            continue

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

                    # Auto-download new works if enabled
                    if sub.auto_download and pool:
                        for work in new_works:
                            try:
                                job_id = uuid.uuid4()
                                async with AsyncSessionLocal() as db_session:
                                    db_session.add(DownloadJob(
                                        id=job_id,
                                        url=work.url,
                                        source=source_name,
                                        status="queued",
                                        progress={},
                                    ))
                                    await db_session.commit()
                                await pool.enqueue_job(
                                    "download_job",
                                    work.url,
                                    source_name,
                                    None,
                                    str(job_id),
                                    None,
                                    _job_id=str(job_id),
                                )
                            except Exception as enq_exc:
                                logger.warning(
                                    "[check_followed] failed to enqueue auto-download for %s: %s",
                                    work.url, enq_exc,
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
        credentials = await get_credential(sub.source)
        if not credentials:
            return {"status": "failed", "error": f"No {sub.source} credentials"}

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
                        for work in new_works:
                            try:
                                job_id = uuid.uuid4()
                                async with AsyncSessionLocal() as db_session:
                                    db_session.add(DownloadJob(
                                        id=job_id, url=work.url,
                                        source=sub.source, status="queued", progress={},
                                    ))
                                    await db_session.commit()
                                await pool.enqueue_job(
                                    "download_job", work.url, sub.source,
                                    None, str(job_id), None,
                                    _job_id=str(job_id),
                                )
                            except Exception as enq_exc:
                                logger.warning("[check_sub] failed to enqueue: %s", enq_exc)
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
