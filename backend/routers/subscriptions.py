"""Subscription management endpoints."""

import logging
from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth, require_role
from core.database import async_session
from core.utils import detect_source
from db.models import Subscription

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscriptions"])

_member = require_role("member")


class CreateSubscriptionRequest(BaseModel):
    url: str
    name: str | None = None
    cron_expr: str | None = None
    auto_download: bool = True


class PatchSubscriptionRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    auto_download: bool | None = None
    cron_expr: str | None = None


@router.get("/")
async def list_subscriptions(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """List subscriptions for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        query = select(Subscription).where(Subscription.user_id == user_id)
        if source:
            query = query.where(Subscription.source == source)
        if enabled is not None:
            query = query.where(Subscription.enabled == enabled)
        query = query.order_by(Subscription.created_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        subs = result.scalars().all()

        count_q = select(sa_func.count(Subscription.id)).where(Subscription.user_id == user_id)
        if source:
            count_q = count_q.where(Subscription.source == source)
        if enabled is not None:
            count_q = count_q.where(Subscription.enabled == enabled)
        total = (await session.execute(count_q)).scalar() or 0

    return {
        "subscriptions": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "source": s.source,
                "source_id": s.source_id,
                "avatar_url": s.avatar_url,
                "enabled": s.enabled,
                "auto_download": s.auto_download,
                "cron_expr": s.cron_expr,
                "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
                "last_item_id": s.last_item_id,
                "last_status": s.last_status,
                "last_error": s.last_error,
                "last_job_id": str(s.last_job_id) if s.last_job_id else None,
                "next_check_at": s.next_check_at.isoformat() if s.next_check_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ],
        "total": total,
    }


@router.post("/")
async def create_subscription(
    req: CreateSubscriptionRequest,
    auth: dict = Depends(_member),
):
    """Create a new subscription."""
    user_id = auth["user_id"]
    source: str | None = detect_source(req.url)
    if source == "unknown":
        source = None

    if req.cron_expr:
        try:
            croniter(req.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")

    async with async_session() as session:
        stmt = pg_insert(Subscription).values(
            user_id=user_id,
            url=req.url,
            name=req.name,
            source=source,
            source_id=None,
            auto_download=req.auto_download,
            cron_expr=req.cron_expr or "0 */2 * * *",
        ).on_conflict_do_update(
            constraint="subscriptions_user_id_url_key",
            set_={
                "name": req.name,
                "auto_download": req.auto_download,
                "cron_expr": req.cron_expr or "0 */2 * * *",
                "enabled": True,
            },
        ).returning(Subscription.id)

        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()

    return {"status": "ok", "id": row.id if row else None, "source": source}


@router.get("/{sub_id}")
async def get_subscription(
    sub_id: int,
    auth: dict = Depends(require_auth),
):
    """Get subscription detail."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
        )).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    return {
        "id": sub.id,
        "name": sub.name,
        "url": sub.url,
        "source": sub.source,
        "source_id": sub.source_id,
        "avatar_url": sub.avatar_url,
        "enabled": sub.enabled,
        "auto_download": sub.auto_download,
        "cron_expr": sub.cron_expr,
        "last_checked_at": sub.last_checked_at.isoformat() if sub.last_checked_at else None,
        "last_item_id": sub.last_item_id,
        "last_status": sub.last_status,
        "last_error": sub.last_error,
        "last_job_id": str(sub.last_job_id) if sub.last_job_id else None,
        "next_check_at": sub.next_check_at.isoformat() if sub.next_check_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }


@router.get("/{sub_id}/jobs")
async def get_subscription_jobs(
    sub_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    auth: dict = Depends(require_auth),
):
    """Get download jobs linked to a subscription."""
    from db.models import DownloadJob, Gallery
    from routers.download import _j

    user_id = auth["user_id"]
    async with async_session() as session:
        # Verify ownership
        sub = (await session.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
        )).scalar_one_or_none()
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

    return {"jobs": [_j(j, gallery_map.get(j.gallery_id)) for j in jobs]}


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
        try:
            croniter(req.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")
        updates["cron_expr"] = req.cron_expr

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with async_session() as session:
        result = await session.execute(
            update(Subscription).where(
                Subscription.id == sub_id,
                Subscription.user_id == user_id,
            ).values(**updates).returning(Subscription.id)
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

        # Cancel active jobs linked to this subscription before deletion.
        # Must run before the DELETE because the FK has ondelete="SET NULL",
        # which would clear subscription_id on the jobs before we can filter by it.
        from db.models import DownloadJob
        active_jobs = (await session.execute(
            select(DownloadJob).where(
                DownloadJob.subscription_id == sub_id,
                DownloadJob.status.in_(["queued", "running"]),
            )
        )).scalars().all()
        for job in active_jobs:
            job.status = "cancelled"
            cancelled_jobs.append(str(job.id))

        await session.delete(sub)
        await session.commit()

    # Set Redis cancel flags for running jobs so workers stop promptly
    if cancelled_jobs:
        from core.redis_client import get_redis
        redis = get_redis()
        for job_id in cancelled_jobs:
            await redis.setex(f"download:cancel:{job_id}", 3600, "1")

    return {"status": "ok", "cancelled_jobs": len(cancelled_jobs)}


@router.post("/{sub_id}/check")
async def check_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Trigger immediate check for a subscription."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
        )).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        arq = request.app.state.arq
        await arq.enqueue_job("check_single_subscription", sub_id)
    except Exception as exc:
        logger.error("Failed to enqueue check_single_subscription: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id}
