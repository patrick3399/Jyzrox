"""Durable subscription pause (ADR 0030).

The subscription row is the source of truth; job rows follow it. Redis pause
keys are only the fast signal for jobs already running.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import DownloadJob, Subscription

# services.download_pause is imported inside the functions: it pulls in
# worker.helpers, whose package init imports worker.download, which imports this
# module. A top-level import would be circular when download_pause loads first.

PAUSE_REASONS = ("manual", "rate_limited", "auth")
_RATE_BASE = timedelta(minutes=30)
_RATE_MAX = timedelta(hours=6)
_RETRY_AFTER_MAX = timedelta(hours=24)


def check_lock_key(sub_id: int) -> str:
    return f"subscription:check_lock:{sub_id}"


def rate_limit_cooldown(halt_count: int, retry_after: int | None) -> timedelta:
    backoff = min(_RATE_BASE * (2 ** min(max(0, halt_count), 16)), _RATE_MAX)
    if retry_after:
        backoff = max(backoff, min(timedelta(seconds=retry_after), _RETRY_AFTER_MAX))
    return backoff


async def pause_subscription(session: AsyncSession, sub_id: int, *, reason: str, until: datetime | None = None) -> dict:
    from services.download_pause import PAUSE_KEY_TTL, pause_key

    if reason not in PAUSE_REASONS:
        raise ValueError(f"unknown pause reason {reason!r}")
    stmt = update(Subscription).where(Subscription.id == sub_id)
    values: dict = {"paused_at": datetime.now(UTC), "paused_reason": reason, "paused_until": until}
    if reason == "rate_limited":
        # Never override a manual or login pause; extend an existing rate limit.
        stmt = stmt.where(or_(Subscription.paused_at.is_(None), Subscription.paused_reason == "rate_limited"))
        values["halt_count"] = Subscription.halt_count + 1
    elif reason == "auth":
        stmt = stmt.where(or_(Subscription.paused_at.is_(None), Subscription.paused_reason != "manual"))
    applied = (await session.execute(stmt.values(**values).returning(Subscription.id))).first() is not None

    active = DownloadJob.subscription_id == sub_id
    not_stopped = DownloadJob.stop_requested_at.is_(None)
    queued = (
        await session.execute(
            update(DownloadJob)
            .where(active, not_stopped, DownloadJob.status == "queued")
            .values(status="paused")
            .returning(DownloadJob.id)
        )
    ).all()
    running_ids = (
        (await session.execute(select(DownloadJob.id).where(active, not_stopped, DownloadJob.status == "running")))
        .scalars()
        .all()
    )
    redis = get_redis()
    for job_id in running_ids:  # signal first; a Redis failure rolls the whole pause back
        await redis.set(pause_key(job_id), b"1", ex=PAUSE_KEY_TTL)
    running = (
        (
            await session.execute(
                update(DownloadJob)
                .where(DownloadJob.id.in_(running_ids), DownloadJob.status == "running")
                .values(status="paused")
                .returning(DownloadJob.id)
            )
        ).all()
        if running_ids
        else []
    )
    await session.commit()
    return {"paused_jobs": len(queued) + len(running), "applied": applied}


async def resume_subscription(session: AsyncSession, sub_id: int, *, only_reason: str | None = None) -> dict:
    from services.download_pause import resume_job

    sub = await session.get(Subscription, sub_id)
    if sub is None:
        return {"status": "skipped", "resumed_jobs": 0}
    if only_reason is not None and sub.paused_reason != only_reason:
        return {"status": "skipped", "resumed_jobs": 0}
    job_ids = (
        (
            await session.execute(
                select(DownloadJob.id)
                .where(
                    DownloadJob.subscription_id == sub_id,
                    DownloadJob.status == "paused",
                    DownloadJob.stop_requested_at.is_(None),
                )
                .order_by(DownloadJob.admission_ticket.asc().nulls_last(), DownloadJob.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    resumed = 0
    for job_id in job_ids:  # jobs first: a crash midway leaves the subscription paused, so resume can be repeated
        job = await session.get(DownloadJob, job_id)
        if job is None or job.status != "paused" or job.stop_requested_at is not None:
            continue
        await resume_job(session, job)
        resumed += 1
    clear: dict = {"paused_at": None, "paused_reason": None, "paused_until": None}
    if only_reason is None:
        clear["halt_count"] = 0
    await session.execute(update(Subscription).where(Subscription.id == sub_id).values(**clear))
    await session.commit()
    return {"status": "ok", "resumed_jobs": resumed}


async def halt_subscription_for_job(job_id: str, reason: str, retry_after: int | None) -> bool:
    """Pause the owning subscription of a halted job. False when it has none."""
    from services.download_pause import pause_key

    async with AsyncSessionLocal() as session:
        job = await session.get(DownloadJob, uuid.UUID(str(job_id)))
        if job is None or job.subscription_id is None:
            return False
        sub = await session.get(Subscription, job.subscription_id)
        until = None
        if reason == "rate_limited":
            until = datetime.now(UTC) + rate_limit_cooldown(sub.halt_count if sub else 0, retry_after)
        await pause_subscription(session, job.subscription_id, reason=reason, until=until)
        # The halted job itself: conditional, never over a stop or a terminal state.
        await session.execute(
            update(DownloadJob)
            .where(
                DownloadJob.id == job.id,
                DownloadJob.status.in_(["running", "paused"]),
                DownloadJob.stop_requested_at.is_(None),
            )
            .values(status="paused", error=f"Paused: {reason}")
        )
        await session.commit()
        await get_redis().delete(pause_key(job.id))  # it is not running any more; resume re-enqueues it
        return True


async def resume_due_rate_limited(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        due = (
            (
                await session.execute(
                    select(Subscription.id).where(
                        Subscription.paused_reason == "rate_limited", Subscription.paused_until <= now
                    )
                )
            )
            .scalars()
            .all()
        )
        resumed = 0
        for sid in due:
            out = await resume_subscription(session, sid, only_reason="rate_limited")
            resumed += out["status"] == "ok"
        return resumed
