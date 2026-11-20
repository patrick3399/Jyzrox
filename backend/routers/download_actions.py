"""Download gallery-action and dashboard endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.auth import gallery_access_filter, has_gallery_write_access, require_role
from core.database import get_db
from core.redis_client import get_redis
from db.models import DownloadJob, Gallery
from services.download_enqueue import ACTIVE_JOB_STATUSES
from services.download_enqueue import enqueue_url as _enqueue
from services.download_mode import (
    DOWNLOAD,
    REPAIR,
    find_gallery_subscription,
)
from services.download_presenter import serialize_download_job

logger = logging.getLogger(__name__)
router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class GalleryActionRequest(BaseModel):
    action: Literal["repair", "update"]
    # Repair only: let images the user purged (ExcludedBlob) back in.
    include_excluded: bool = False


@router.post("/galleries/{gallery_id}/action")
async def gallery_action(
    gallery_id: int,
    req: GalleryActionRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Gallery page "repair" / "update" (outdated).

    * ``update`` on a subscription's gallery triggers a subscription check
      (incremental, honours the boundary); otherwise a plain re-download.
    * ``repair`` re-fetches against an empty shadow archive so files that were
      archived but never imported come back; on a subscription's gallery it
      inherits the subscription's download options.
    """
    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")
    if not await has_gallery_write_access(db, gallery.id, gallery.created_by_user_id, auth):
        raise HTTPException(status_code=403, detail="Gallery write access is required")
    # The access filter already hides trashed galleries; keep the guard so a
    # download can never mutate or resurrect one (BE-T17) if that ever changes.
    if gallery.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Gallery is in the trash")

    active_job = (
        await db.execute(
            select(DownloadJob.id)
            .where(DownloadJob.gallery_id == gallery.id, DownloadJob.status.in_(ACTIVE_JOB_STATUSES))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(status_code=409, detail="Gallery already has an active download job")

    sub = await find_gallery_subscription(db, gallery.id, auth["user_id"])

    # A paused subscription starts no work (ADR 0030): neither its check nor a
    # repair that inherits it. Answer like POST /subscriptions/{id}/check does.
    if sub is not None and sub.paused_at is not None:
        raise HTTPException(status_code=409, detail="Subscription is paused")

    if req.action == "update" and sub is not None:
        try:
            await core.queue.enqueue("check_single_subscription", _timeout=600, sub_id=sub.id)
        except Exception as exc:
            logger.error("[gallery_action] failed to enqueue check_single_subscription for sub %d: %s", sub.id, exc)
            raise HTTPException(status_code=503, detail="Failed to enqueue subscription check") from exc
        return {"kind": "subscription_check", "subscription_id": sub.id, "status": "queued"}

    url = sub.url if (sub is not None and req.action == "repair") else gallery.source_url
    if not url or not url.strip():
        raise HTTPException(status_code=422, detail="Gallery has no source URL to download from")

    if req.action == "update":
        # No gallery_id preset: an attached job skips the identity upsert in the
        # importer, so the gallery's title/tags would stop refreshing. (Repair
        # re-fetches missing files into an existing gallery, so it presets it.)
        result = await _enqueue(url, db, mode=DOWNLOAD, user_id=auth["user_id"])
        kind = "download"
    else:
        options = dict(sub.download_options or {}) if sub is not None else {}
        if req.include_excluded:
            options["include_excluded"] = True
        result = await _enqueue(
            url,
            db,
            options=options or None,
            mode=REPAIR,
            subscription_id=sub.id if sub is not None else None,
            gallery_id=gallery.id,
            user_id=auth["user_id"],
        )
        kind = "repair"

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.DOWNLOAD_ENQUEUED,
        actor_user_id=auth["user_id"],
        resource_type="download_job",
        resource_id=result.get("job_id"),
    )
    return {"kind": kind, **result}


@router.get("/dashboard")
async def get_dashboard(auth: dict = Depends(_admin), db: AsyncSession = Depends(get_db)):
    """Live download dashboard snapshot (admin only)."""
    import asyncio
    import json as _json
    from datetime import UTC, datetime

    from core.adaptive import AdaptiveState, adaptive_engine
    from core.redis_client import is_rate_limit_boosted
    from core.site_config import site_config_service
    from worker.constants import DISK_LOW_KEY
    from worker.helpers import check_disk_space

    r = get_redis()

    # Check cache first (3s TTL)
    cached = await r.get("dashboard:snapshot")
    if cached:
        raw = cached.decode() if isinstance(cached, bytes) else cached
        return _json.loads(raw)

    # DB queries (sequential — same session cannot run concurrent queries)
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    active_stmt = select(DownloadJob).where(DownloadJob.status == "running").order_by(DownloadJob.created_at)
    queued_stmt = (
        select(DownloadJob).where(DownloadJob.status.in_(["queued"])).order_by(DownloadJob.created_at).limit(50)
    )
    today_stmt = select(func.count()).where(DownloadJob.created_at >= today_start)
    # Combined: per-source counts + global running/queued totals in one query
    admission_group = func.coalesce(DownloadJob.admission_key, DownloadJob.source)
    source_counts_stmt = (
        select(admission_group, DownloadJob.status, func.count())
        .where(DownloadJob.status.in_(["running", "queued"]))
        .group_by(admission_group, DownloadJob.status)
    )
    holder_counts_stmt = (
        select(admission_group, func.count()).where(DownloadJob.admission_token.is_not(None)).group_by(admission_group)
    )

    active_jobs = (await db.execute(active_stmt)).scalars().all()
    queued_jobs = (await db.execute(queued_stmt)).scalars().all()
    total_today = (await db.execute(today_stmt)).scalar_one()
    source_counts = (await db.execute(source_counts_stmt)).all()
    holder_counts = dict((await db.execute(holder_counts_stmt)).all())

    # Redis calls (parallel)
    boost, all_params = await asyncio.gather(
        is_rate_limit_boosted(),
        site_config_service.get_all_download_params(),
    )

    # Parse per-source running/queued counts + derive global totals
    source_running: dict[str, int] = {}
    source_queued: dict[str, int] = {}
    total_running = 0
    total_queued = 0
    for src, st, cnt in source_counts:
        if st == "running":
            source_running[src] = cnt
            total_running += cnt
        else:
            source_queued[src] = cnt
            total_queued += cnt

    # Compute avg speed from active jobs
    source_speeds: dict[str, list[float]] = {}
    admission_sources: dict[str, str] = {}
    for job in active_jobs:
        key = job.admission_key or job.source or "unknown"
        admission_sources[key] = job.source or key
        if job.progress and isinstance(job.progress, dict):
            speed = job.progress.get("speed", 0)
            if speed:
                source_speeds.setdefault(key, []).append(speed)
    for job in queued_jobs:
        key = job.admission_key or job.source or "unknown"
        admission_sources[key] = job.source or key

    # Merge all known sources
    all_sources = sorted(set(all_params.keys()) | set(source_running.keys()) | set(source_queued.keys()))
    adaptive_states = await adaptive_engine.get_states_batch(
        sorted({admission_sources.get(src, src) for src in all_sources})
    )
    site_stats: dict[str, dict] = {}
    for src in all_sources:
        config_source = admission_sources.get(src, src)
        adaptive_state = adaptive_states.get(config_source) or AdaptiveState()
        params = all_params.get(config_source)
        sem_info = {
            "used": holder_counts.get(src, 0),
            "max": params.concurrency if params else 2,
        }
        speeds = source_speeds.get(src, [])
        avg_speed = round(sum(speeds) / len(speeds), 2) if speeds else 0

        delay_ms = 0
        if params and params.sleep_request is not None:
            if isinstance(params.sleep_request, tuple):
                delay_ms = round(params.sleep_request[0] * 1000)
            else:
                delay_ms = round(params.sleep_request * 1000)

        site_stats[src] = {
            "semaphore": sem_info,
            "queued": source_queued.get(src, 0),
            "running": source_running.get(src, 0),
            "avg_speed": avg_speed,
            "current_delay_ms": delay_ms,
            "adaptive": {
                "last_429_at": adaptive_state.last_signal_at if adaptive_state.last_signal == "http_429" else None,
            },
        }

    # Disk status
    disk_low_val = await r.get(DISK_LOW_KEY)
    if disk_low_val is not None:
        free_gb = float(disk_low_val.decode() if isinstance(disk_low_val, bytes) else disk_low_val)
        disk_ok = False
    else:
        disk_ok, free_gb = check_disk_space("/data")

    result = {
        "active_jobs": [serialize_download_job(j) for j in active_jobs],
        "queued_jobs": [serialize_download_job(j) for j in queued_jobs],
        "site_stats": site_stats,
        "global": {
            "boost_mode": boost,
            "total_running": total_running,
            "total_queued": total_queued,
            "total_today": total_today,
        },
        "system": {
            "disk_free_gb": free_gb,
            "disk_ok": disk_ok,
        },
    }

    await r.set("dashboard:snapshot", _json.dumps(result, default=str), ex=3)
    return result
