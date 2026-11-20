"""External API status, gallery list and detail endpoints."""

import logging
import shutil

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text

from core.auth import gallery_access_filter
from core.config import settings
from core.database import async_session
from db.models import DownloadJob, Gallery
from services.external_auth import verify_api_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def system_status(token_data: dict = Depends(verify_api_token)):
    """Returns basic system status and stats for external dashboards (e.g. Homepage)."""

    async with async_session() as session:
        # Fast estimated counts via pg_stat (< 1ms vs 2-5s for COUNT(*) on large tables)
        row_estimates = (
            await session.execute(
                text(
                    "SELECT relname, n_live_tup::bigint FROM pg_stat_user_tables "
                    "WHERE relname IN ('galleries', 'images', 'tags')"
                )
            )
        ).all()
        counts = {r[0]: r[1] for r in row_estimates}
        gallery_count = counts.get("galleries", 0)
        image_count = counts.get("images", 0)
        tag_count = counts.get("tags", 0)

        # Active downloads: small result set, exact COUNT is fine
        active_downloads = (
            await session.execute(
                select(func.count()).select_from(DownloadJob).where(DownloadJob.status.in_(["queued", "running"]))
            )
        ).scalar()

    try:
        usage = shutil.disk_usage(settings.data_gallery_path)
        disk_total = usage.total
        disk_free = usage.free
    except OSError:
        disk_total = 0
        disk_free = 0

    try:
        import asyncio as _asyncio

        proc = await _asyncio.create_subprocess_exec(
            "df",
            "-i",
            "--output=itotal,iused,iavail,ipcent",
            settings.data_cas_path,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=5)
        lines = stdout.decode().strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            inode_total = int(parts[0])
            inode_used = int(parts[1])
            inode_free = int(parts[2])
            inode_percent = parts[3]  # e.g. "54%"
        else:
            inode_total = inode_used = inode_free = 0
            inode_percent = "N/A"
    except Exception:
        inode_total = inode_used = inode_free = 0
        inode_percent = "N/A"

    return {
        "status": "online",
        "version": "0.1",
        "stats": {
            "galleries": gallery_count,
            "images": image_count,
            "tags": tag_count,
            "active_downloads": active_downloads,
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total,
        },
        "inodes": {
            "total": inode_total,
            "used": inode_used,
            "free": inode_free,
            "percent": inode_percent,
        },
    }


# ── Galleries ─────────────────────────────────────────────────────────


@router.get("/galleries")
async def list_galleries(
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    source: str | None = Query(default=None),
    q: str | None = Query(default=None),
    favorited: bool | None = Query(default=None),
    min_rating: int | None = Query(default=None, ge=0, le=5),
    token_data: dict = Depends(verify_api_token),
):
    """List local library galleries (paginated)."""
    filters = []
    if source:
        filters.append(Gallery.source == source)
    if q:
        filters.append(Gallery.title.ilike(f"%{q}%"))
    if favorited is not None:
        if favorited:
            from db.models import UserFavorite

            filters.append(
                Gallery.id.in_(select(UserFavorite.gallery_id).where(UserFavorite.user_id == token_data["user_id"]))
            )
    if min_rating is not None:
        from db.models import UserRating

        filters.append(
            Gallery.id.in_(
                select(UserRating.gallery_id).where(
                    UserRating.user_id == token_data["user_id"],
                    UserRating.rating >= min_rating,
                )
            )
        )

    async with async_session() as session:
        count_result = await session.execute(
            select(func.count()).select_from(Gallery).where(*filters, gallery_access_filter(token_data))
        )
        total = count_result.scalar() or 0

        data_query = (
            select(Gallery)
            .where(*filters, gallery_access_filter(token_data))
            .order_by(Gallery.added_at.desc())
            .limit(limit)
            .offset(page * limit)
        )
        rows = (await session.execute(data_query)).scalars().all()

    galleries = []
    for r in rows:
        galleries.append(
            {
                "id": r.id,
                "source": r.source,
                "source_id": r.source_id,
                "title": r.title,
                "title_jpn": r.title_jpn,
                "category": r.category,
                "language": r.language,
                "pages": r.pages,
                "posted_at": r.posted_at.isoformat() if r.posted_at else None,
                "added_at": r.added_at.isoformat() if r.added_at else None,
                "rating": r.rating,
                "favorited": False,
                "uploader": r.uploader,
                "download_status": r.download_status,
                "tags": r.tags_array or [],
            }
        )

    return {"total": total, "page": page, "galleries": galleries}


@router.get("/galleries/{gallery_id}")
async def get_gallery(
    gallery_id: int,
    token_data: dict = Depends(verify_api_token),
):
    """Get a single gallery by ID."""
    async with async_session() as session:
        r = (
            await session.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))
        ).scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="Gallery not found")

    return {
        "id": r.id,
        "source": r.source,
        "source_id": r.source_id,
        "title": r.title,
        "title_jpn": r.title_jpn,
        "category": r.category,
        "language": r.language,
        "pages": r.pages,
        "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        "added_at": r.added_at.isoformat() if r.added_at else None,
        "rating": r.rating,
        "favorited": False,
        "uploader": r.uploader,
        "download_status": r.download_status,
        "tags": r.tags_array or [],
    }
