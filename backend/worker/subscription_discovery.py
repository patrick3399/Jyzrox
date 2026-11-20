"""Subscription discovery enqueue and pause/cron helpers."""

import uuid
from datetime import UTC, datetime

from croniter import croniter
from sqlalchemy import select, update

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.utils import normalize_download_url
from db.models import DownloadJob, Subscription
from plugins.models import NewWork
from services.download_admission import admission_key_for
from services.download_mode import subscription_mode
from worker.constants import logger


def _compute_next_check(cron_expr: str | None, base: datetime) -> datetime | None:
    """Compute the next scheduled check time from a cron expression.

    Returns ``None`` when the cron expression is missing or unparseable so the
    caller leaves the existing ``next_check_at`` unchanged rather than crashing
    the enqueue path.
    """
    if not cron_expr:
        return None
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception:
        return None


async def _enqueue_discovered_works(ctx: dict, sub, subscriber, *, force_full_scan: bool) -> dict:
    """Discover a subscription's new works via the registry subscriber and queue each as its own gallery job."""
    from core.redis_client import publish_job_event
    from services.credential import get_credential

    source = sub.source or subscriber.meta.source_id

    try:
        credential = await get_credential(source)
        result = await subscriber.discover_new_works(
            sub.url,
            None if force_full_scan else sub.last_item_id,
            sub.download_options if isinstance(sub.download_options, dict) else {},
            credential,
        )
    except Exception as exc:
        logger.warning("[subscription] %s discovery failed for sub=%d: %s", source, sub.id, exc)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription).where(Subscription.id == sub.id).values(last_status="failed", last_error=str(exc))
            )
            await session.commit()
        return {"status": "failed", "error": str(exc)}
    works, latest_id = result.works, result.latest_id

    options = {"job_context": "subscription", **result.job_options}
    mode = subscription_mode(has_boundary=bool(sub.last_item_id), force_full_scan=force_full_scan)
    enqueued: list[tuple[uuid.UUID, NewWork]] = []
    async with AsyncSessionLocal() as session:
        for work in works:
            canonical_url = normalize_download_url(work.url)
            active = (
                await session.execute(
                    select(DownloadJob.id)
                    .where(
                        DownloadJob.canonical_url == canonical_url,
                        DownloadJob.user_id == sub.user_id,
                        DownloadJob.status.in_(["queued", "running", "paused"]),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if active:
                continue
            job_id = uuid.uuid4()
            session.add(
                DownloadJob(
                    id=job_id,
                    url=canonical_url,
                    canonical_url=canonical_url,
                    source=source,
                    status="queued",
                    progress={},
                    options=options,
                    mode=mode,
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                    admission_key=admission_key_for(source, canonical_url),
                )
            )
            enqueued.append((job_id, work))
        await session.commit()

    for job_id, work in enqueued:
        await core.queue.enqueue(
            "download_job",
            _job_id=str(job_id),
            _timeout=settings.download_job_timeout,
            url=work.url,
            source=source,
            options=options,
            db_job_id=str(job_id),
            total=None,
        )

    now = datetime.now(UTC)
    values = {
        "last_checked_at": now,
        "last_success_at": now,
        "last_job_id": enqueued[-1][0] if enqueued else None,
        "last_item_id": latest_id or sub.last_item_id,
        "last_status": "queued" if enqueued else "up_to_date",
        "last_error": None,
        "source_id": subscriber.subscription_identity(sub.url),
    }
    if sub.group_id is None:
        next_check = _compute_next_check(sub.cron_expr, now)
        if next_check is not None:
            values["next_check_at"] = next_check
    async with AsyncSessionLocal() as session:
        await session.execute(update(Subscription).where(Subscription.id == sub.id).values(**values))
        await session.commit()

    await publish_job_event(
        {
            "type": "subscription_checked",
            "sub_id": sub.id,
            "status": "ok",
            "job_id": str(enqueued[-1][0]) if enqueued else None,
            "user_id": sub.user_id,
            "discovered": len(works),
            "enqueued": len(enqueued),
        }
    )
    return {"status": "ok", "job_id": str(enqueued[-1][0]) if enqueued else None, "enqueued": len(enqueued)}


async def _current_paused_at(sub_id: int):
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(Subscription.paused_at).where(Subscription.id == sub_id))
        ).scalar_one_or_none()
