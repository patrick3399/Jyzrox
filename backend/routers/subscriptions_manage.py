"""Subscription bulk-move, detail, job-history, update and delete endpoints."""

from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select, update

from core.auth import require_auth, require_role
from core.database import async_session
from core.utils import validate_cron
from db.models import Subscription
from services.download_policy import normalize_download_options
from services.subscription_view import checking_flags as _checking_flags
from services.subscription_view import serialize_subscription as _serialize_subscription

router = APIRouter()

_member = require_role("member")


class PatchSubscriptionRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    auto_download: bool | None = None
    cron_expr: str | None = None
    group_id: int | None = None
    download_options: dict | None = None


class BulkMoveRequest(BaseModel):
    sub_ids: list[int]
    group_id: int | None


@router.post("/bulk-move")
async def bulk_move_subscriptions(
    req: BulkMoveRequest,
    auth: dict = Depends(_member),
):
    """Move subscriptions to a different group."""
    user_id = auth["user_id"]
    async with async_session() as session:
        result = await session.execute(
            update(Subscription)
            .where(
                Subscription.id.in_(req.sub_ids),
                Subscription.user_id == user_id,
            )
            .values(group_id=req.group_id)
        )
        await session.commit()

    return {"status": "ok", "updated": result.rowcount}  # type: ignore[union-attr]


@router.get("/{sub_id}")
async def get_subscription(
    sub_id: int,
    auth: dict = Depends(require_auth),
):
    """Get subscription detail."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    checking = await _checking_flags([sub.id])
    return _serialize_subscription(sub, checking=checking[0])


@router.get("/{sub_id}/jobs")
async def get_subscription_jobs(
    sub_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    auth: dict = Depends(require_auth),
):
    """Get download jobs linked to a subscription."""
    from db.models import DownloadJob, Gallery
    from services.download_presenter import serialize_download_job

    user_id = auth["user_id"]
    async with async_session() as session:
        # Verify ownership
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Get linked jobs
        stmt = (
            select(DownloadJob)
            .where(DownloadJob.subscription_id == sub_id)
            .order_by(DownloadJob.created_at.desc())
            .limit(limit)
        )
        jobs = (await session.execute(stmt)).scalars().all()

        # Load galleries for jobs that have a gallery_id
        gallery_ids = [j.gallery_id for j in jobs if j.gallery_id]
        gallery_map = {}
        if gallery_ids:
            gs = (await session.execute(select(Gallery).where(Gallery.id.in_(gallery_ids)))).scalars().all()
            gallery_map = {g.id: g for g in gs}

    return {"jobs": [serialize_download_job(j, gallery_map.get(j.gallery_id)) for j in jobs]}


@router.patch("/{sub_id}")
async def update_subscription(
    sub_id: int,
    req: PatchSubscriptionRequest,
    auth: dict = Depends(require_auth),
):
    """Update a subscription."""
    user_id = auth["user_id"]

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.enabled is not None:
        updates["enabled"] = req.enabled
    if req.auto_download is not None:
        updates["auto_download"] = req.auto_download
    if req.cron_expr is not None:
        validate_cron(req.cron_expr)
        updates["cron_expr"] = req.cron_expr
        # Reschedule from the new cron right away. Leaving next_check_at on the
        # old schedule would keep the previous interval active until the next
        # check completed. Grouped subs ignore it, but it is what takes effect
        # once such a sub is moved back out of its group.
        updates["next_check_at"] = croniter(req.cron_expr, datetime.now(UTC)).get_next(datetime)
    if req.group_id is not None:
        updates["group_id"] = req.group_id
    if req.download_options is not None:
        # Policy validation needs the source and URL from the owned subscription
        # rather than trusting caller-supplied identifiers.
        async with async_session() as session:
            owned = (
                await session.execute(
                    select(Subscription.source, Subscription.url).where(
                        Subscription.id == sub_id, Subscription.user_id == user_id
                    )
                )
            ).first()
        if owned is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        try:
            updates["download_options"] = await normalize_download_options(
                owned.url, owned.source, req.download_options
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid download options: {exc}") from exc

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with async_session() as session:
        result = await session.execute(
            update(Subscription)
            .where(
                Subscription.id == sub_id,
                Subscription.user_id == user_id,
            )
            .values(**updates)
            .returning(Subscription.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "ok"}


@router.delete("/{sub_id}")
async def delete_subscription(
    sub_id: int,
    auth: dict = Depends(require_auth),
):
    """Delete a subscription and cancel any active download jobs."""
    user_id = auth["user_id"]
    cancelled_jobs: list[str] = []
    async with async_session() as session:
        # Verify ownership first — before touching any jobs
        sub = await session.get(Subscription, sub_id)
        if not sub or sub.user_id != user_id:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Delete finished jobs linked to this subscription before cancelling
        # active ones; otherwise newly-cancelled active jobs would be removed.
        # Must run before the DELETE because the FK has ondelete="SET NULL",
        # which would clear subscription_id and leak jobs into the Queue page.
        from db.models import DownloadJob

        terminal_job_ids = (
            (
                await session.execute(
                    select(DownloadJob.id).where(
                        DownloadJob.subscription_id == sub_id,
                        DownloadJob.status.in_(["done", "failed", "cancelled", "partial"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        if terminal_job_ids:
            await session.execute(
                delete(DownloadJob).where(
                    DownloadJob.id.in_(terminal_job_ids),
                )
            )

        active_jobs = (
            (
                await session.execute(
                    select(DownloadJob).where(
                        DownloadJob.subscription_id == sub_id,
                        DownloadJob.status.in_(["queued", "running", "paused"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        for job in active_jobs:
            job.status = "cancelled"
            cancelled_jobs.append(str(job.id))

        if cancelled_jobs:
            from core.redis_client import get_redis

            redis = get_redis()
            for job_id in cancelled_jobs:
                await redis.setex(f"download:cancel:{job_id}", 3600, "1")

        await session.delete(sub)
        await session.commit()

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_DELETED, actor_user_id=auth["user_id"], resource_type="subscription", resource_id=sub_id
    )
    return {"status": "ok", "cancelled_jobs": len(cancelled_jobs)}
