"""Subscription management endpoints."""

import logging
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

import core.queue
from core.auth import gallery_access_filter, require_auth, require_role
from core.database import async_session
from core.utils import detect_source, normalize_subscription_url, validate_cron
from db.models import DownloadJob, Gallery, Subscription
from services.download_policy import normalize_source_options

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscriptions"])

_member = require_role("member")


def _build_subscription_upsert(
    *,
    user_id: int,
    url: str,
    name: str | None,
    source: str | None,
    auto_download: bool,
    cron_expr: str,
    next_check,
    group_id: int | None,
    download_options: dict | None = None,
):
    """Build the create-or-upsert statement for a subscription.

    On conflict (same user_id+url, i.e. re-subscribing) the schedule fields are
    refreshed alongside cron_expr: ``next_check_at`` is recomputed from the new
    cron and ``source`` is re-synced from URL detection. Leaving next_check_at
    stale here would keep the old schedule active despite the updated cron
    (edge-case audit #10). ``group_id`` is intentionally NOT updated on conflict
    — group moves go through PATCH / bulk-move, so an upsert without an explicit
    group must not yank a subscription out of its existing group.
    """
    return (
        pg_insert(Subscription)
        .values(
            user_id=user_id,
            url=url,
            name=name,
            source=source,
            source_id=None,
            auto_download=auto_download,
            cron_expr=cron_expr,
            next_check_at=next_check,
            group_id=group_id,
            download_options=download_options or {},
        )
        .on_conflict_do_update(
            constraint="subscriptions_user_id_url_key",
            set_={
                "name": name,
                "source": source,
                "auto_download": auto_download,
                "cron_expr": cron_expr,
                "next_check_at": next_check,
                "enabled": True,
                "download_options": download_options or {},
            },
        )
        .returning(Subscription.id)
    )


class CreateSubscriptionRequest(BaseModel):
    url: str
    name: str | None = None
    cron_expr: str | None = None
    auto_download: bool = True
    group_id: int | None = None
    download_options: dict | None = None


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


def _serialize_subscription(s, gallery: Gallery | None = None) -> dict:
    data = {
        "id": s.id,
        "name": s.name,
        "url": s.url,
        "source": s.source,
        "source_id": s.source_id,
        "avatar_url": s.avatar_url,
        "enabled": s.enabled,
        "auto_download": s.auto_download,
        "cron_expr": s.cron_expr,
        "group_id": s.group_id,
        "download_options": s.download_options or {},
        "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
        "last_item_id": s.last_item_id,
        "last_status": s.last_status,
        "last_error": s.last_error,
        "last_job_id": str(s.last_job_id) if s.last_job_id else None,
        "next_check_at": s.next_check_at.isoformat() if s.next_check_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if gallery:
        data["gallery_id"] = gallery.id
        data["gallery_source"] = gallery.source
        data["gallery_source_id"] = gallery.source_id
    return data


@router.get("/")
async def list_subscriptions(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    group_id: int | None = Query(default=None),
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
        if group_id is not None:
            query = query.where(Subscription.group_id == group_id)
        query = query.order_by(Subscription.created_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        subs = result.scalars().all()

        gallery_by_sub_id: dict[int, Gallery] = {}
        if subs:
            sub_ids = [s.id for s in subs]
            job_gallery_rows = (
                await session.execute(
                    select(DownloadJob.subscription_id, Gallery)
                    .join(Gallery, Gallery.id == DownloadJob.gallery_id)
                    .where(
                        DownloadJob.subscription_id.in_(sub_ids),
                        DownloadJob.gallery_id.is_not(None),
                        gallery_access_filter(auth),
                    )
                    .order_by(DownloadJob.subscription_id.asc(), DownloadJob.created_at.desc())
                )
            ).all()
            for sub_id, gallery in job_gallery_rows:
                gallery_by_sub_id.setdefault(sub_id, gallery)

            # Keep the link stable even if old download jobs are cleaned up.
            urls_missing_job_gallery = [s.url for s in subs if s.id not in gallery_by_sub_id]
            if urls_missing_job_gallery:
                source_url_rows = (
                    (
                        await session.execute(
                            select(Gallery)
                            .where(Gallery.source_url.in_(urls_missing_job_gallery), gallery_access_filter(auth))
                            .order_by(Gallery.source_url.asc(), Gallery.added_at.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
                gallery_by_source_url: dict[str, Gallery] = {}
                for gallery in source_url_rows:
                    if gallery.source_url:
                        gallery_by_source_url.setdefault(gallery.source_url, gallery)
                for sub in subs:
                    if sub.id not in gallery_by_sub_id:
                        gallery = gallery_by_source_url.get(sub.url)
                        if gallery:
                            gallery_by_sub_id[sub.id] = gallery

        count_q = select(sa_func.count(Subscription.id)).where(Subscription.user_id == user_id)
        if source:
            count_q = count_q.where(Subscription.source == source)
        if enabled is not None:
            count_q = count_q.where(Subscription.enabled == enabled)
        if group_id is not None:
            count_q = count_q.where(Subscription.group_id == group_id)
        total = (await session.execute(count_q)).scalar() or 0

    return {
        "subscriptions": [_serialize_subscription(s, gallery_by_sub_id.get(s.id)) for s in subs],
        "total": total,
    }


@router.post("/")
async def create_subscription(
    req: CreateSubscriptionRequest,
    auth: dict = Depends(_member),
):
    """Create a new subscription."""
    user_id = auth["user_id"]
    normalized_url = normalize_subscription_url(req.url)
    source: str | None = detect_source(normalized_url)
    if source == "unknown":
        source = None

    if req.cron_expr:
        validate_cron(req.cron_expr)

    cron_expr = req.cron_expr or "0 */2 * * *"
    download_options = req.download_options or {}
    try:
        download_options = normalize_source_options(source, download_options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Fanbox download policy: {exc}") from exc
    from datetime import datetime

    from croniter import croniter

    next_check = croniter(cron_expr, datetime.now(UTC)).get_next(datetime)

    async with async_session() as session:
        existing = (
            await session.execute(
                select(Subscription.id).where(
                    Subscription.user_id == user_id,
                    Subscription.url == normalized_url,
                )
            )
        ).scalar_one_or_none()

        stmt = _build_subscription_upsert(
            user_id=user_id,
            url=normalized_url,
            name=req.name,
            source=source,
            auto_download=req.auto_download,
            cron_expr=cron_expr,
            next_check=next_check,
            group_id=req.group_id,
            download_options=download_options,
        )

        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_CREATED,
        actor_user_id=auth["user_id"],
        resource_type="subscription",
        resource_id=row.id if row else None,
    )
    return {"status": "ok", "id": row.id if row else None, "source": source, "duplicate": existing is not None}


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

    return _serialize_subscription(sub)


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
    if req.group_id is not None:
        updates["group_id"] = req.group_id
    if req.download_options is not None:
        # Policy validation needs the source from the owned subscription rather
        # than trusting a caller-supplied source identifier.
        async with async_session() as session:
            source = (
                await session.execute(
                    select(Subscription.source).where(Subscription.id == sub_id, Subscription.user_id == user_id)
                )
            ).scalar_one_or_none()
        try:
            updates["download_options"] = normalize_source_options(source or "", req.download_options)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid Fanbox download policy: {exc}") from exc

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


@router.post("/{sub_id}/check")
async def check_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Trigger immediate check for a subscription."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        await core.queue.enqueue("check_single_subscription", _timeout=600, sub_id=sub_id)
    except Exception as exc:
        logger.error("Failed to enqueue check_single_subscription: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id}


@router.post("/{sub_id}/backfill")
async def backfill_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(_member),
):
    """Trigger a force re-scan for a subscription.

    Bypasses both the incremental ``date-after`` filter and gallery-dl's
    archive so the current remote timeline is downloaded again. Importer-side
    de-duplication keeps existing local rows and social ordering preserves
    already-downloaded items even if their remote posts have disappeared.
    """
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        await core.queue.enqueue("check_single_subscription", _timeout=600, sub_id=sub_id, force_full_scan=True)
    except Exception as exc:
        logger.error("Failed to enqueue force re-scan for sub %d: %s", sub_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id, "mode": "force_rescan"}
