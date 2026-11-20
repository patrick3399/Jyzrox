"""Download job listing, stats and URL preview endpoints."""

import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.database import get_db
from core.utils import detect_source, detect_source_info, get_supported_sites
from db.models import DownloadJob, Gallery
from services.download_enqueue import ACTIVE_JOB_STATUSES
from services.download_presenter import serialize_download_job
from services.gallery_lifecycle import settle_stale_downloading_galleries

logger = logging.getLogger(__name__)
router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class PreviewResponse(BaseModel):
    source: str
    preview_available: bool
    title: str | None = None
    pages: int | None = None
    tags: list[str] | None = None
    uploader: str | None = None
    rating: float | None = None
    thumb_url: str | None = None
    category: str | None = None


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    exclude_subscription: bool = Query(default=False),
    subscription_only: bool = Query(default=False),
    active_only: bool = Query(default=False),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if subscription_only and exclude_subscription:
        raise HTTPException(
            status_code=422,
            detail="subscription_only and exclude_subscription are mutually exclusive",
        )
    is_admin = auth["role"] == "admin"
    base_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]
    if exclude_subscription:
        base_filter.append(DownloadJob.subscription_id.is_(None))
    if subscription_only:
        base_filter.append(DownloadJob.subscription_id.is_not(None))
    if active_only:
        base_filter.append(DownloadJob.status.in_(ACTIVE_JOB_STATUSES))

    if status:
        conditions = [DownloadJob.status == status] + base_filter
        stmt_filtered = select(DownloadJob).where(*conditions)
        total = (await db.execute(select(func.count()).select_from(stmt_filtered.subquery()))).scalar_one()
        stmt = stmt_filtered.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    else:
        if is_admin and not base_filter:
            # Fast estimated count for unfiltered admin queries
            total = (
                await db.execute(
                    text("SELECT n_live_tup::bigint FROM pg_stat_user_tables WHERE relname = 'download_jobs'")
                )
            ).scalar_one_or_none() or 0
            stmt = select(DownloadJob).order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
        else:
            stmt_filtered = select(DownloadJob).where(*base_filter)
            total = (await db.execute(select(func.count()).select_from(stmt_filtered.subquery()))).scalar_one()
            stmt = stmt_filtered.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()

    # Batch-load galleries for jobs that have gallery_id
    gallery_ids = [j.gallery_id for j in jobs if j.gallery_id]
    gallery_map: dict[int, Gallery] = {}
    if gallery_ids:
        gs = (await db.execute(select(Gallery).where(Gallery.id.in_(gallery_ids)))).scalars().all()
        gallery_map = {g.id: g for g in gs}

    return {"total": total, "jobs": [serialize_download_job(j, gallery_map.get(j.gallery_id)) for j in jobs]}


@router.delete("/jobs")
async def clear_finished_jobs(
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Delete all completed, failed, and cancelled jobs."""
    conditions = [DownloadJob.status.in_(["done", "failed", "cancelled", "partial"])]
    if auth["role"] != "admin":
        conditions.append(DownloadJob.user_id == auth["user_id"])

    gallery_ids = (
        (
            await db.execute(
                select(DownloadJob.gallery_id).where(
                    *conditions,
                    DownloadJob.gallery_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    await settle_stale_downloading_galleries(db, gallery_ids)

    stmt = delete(DownloadJob).where(*conditions)
    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/stats")
async def get_stats(
    exclude_subscription: bool = Query(default=False),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return counts of running and finished jobs for nav badge polling."""
    is_admin = auth["role"] == "admin"
    user_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]
    if exclude_subscription:
        user_filter.append(DownloadJob.subscription_id.is_(None))
    running_count = (
        await db.execute(select(func.count()).where(DownloadJob.status.in_(ACTIVE_JOB_STATUSES), *user_filter))
    ).scalar_one()
    finished_count = (
        await db.execute(
            select(func.count()).where(DownloadJob.status.in_(["done", "failed", "cancelled", "partial"]), *user_filter)
        )
    ).scalar_one()
    return {"running": running_count, "finished": finished_count}


@router.get("/check-url")
async def check_url(
    url: str = Query(...),
    _: dict = Depends(require_auth),
):
    """Check whether a URL is from a known supported site."""
    from plugins.registry import plugin_registry

    entry = detect_source_info(url)
    if entry is not None:
        return {
            "supported": True,
            "source_id": entry["source_id"],
            "name": entry["name"],
            "category": entry["category"],
            "supports_media_policy": await plugin_registry.supports_media_policy(url),
        }

    # Not in registry — treat as supported if it looks like a valid URL (gallery-dl fallback)
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme and parsed.netloc:
            return {
                "supported": True,
                "source_id": "gallery_dl",
                "name": "gallery-dl",
                "category": "other",
                "supports_media_policy": await plugin_registry.supports_media_policy(url),
            }
    except Exception:
        pass

    return {"supported": False, "supports_media_policy": False}


@router.get("/supported-sites")
async def supported_sites(
    _: dict = Depends(require_auth),
):
    """Return all supported download sites grouped by category."""
    return {"categories": get_supported_sites()}


@router.get("/preview", response_model=PreviewResponse)
async def preview_url(
    url: str = Query(...),
    _: dict = Depends(require_auth),
):
    """Preview metadata for a URL before downloading.

    Returns structured preview data for supported sources (EH, Pixiv).
    For gallery-dl sites without a dedicated client, returns preview_available=False
    with basic site info so the frontend can still confirm the URL is recognised.
    """
    source = detect_source(url)
    if source == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported URL")

    from plugins.registry import plugin_registry

    for plugin in plugin_registry.list_previewable():
        try:
            data = await plugin.preview_url(url)
        except Exception as exc:
            logger.warning("[preview] %s preview failed for %s: %s", plugin.meta.source_id, url, exc)
            continue
        if data is not None:
            return PreviewResponse(preview_available=True, **data.model_dump())

    # Fallback for gallery-dl sites (and plugin sources when metadata fetch fails)
    site_info = detect_source_info(url)
    return PreviewResponse(
        source=source,
        preview_available=False,
        title=site_info.get("name") if site_info else None,
        category=site_info.get("category") if site_info else None,
    )
