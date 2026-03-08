"""External API endpoints for third-party integrations."""

import hashlib
import shutil
import time
import uuid as _uuid

import psutil
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select, update

from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import ApiToken, DownloadJob, Gallery, Image, Tag

router = APIRouter(tags=["external"])


async def verify_api_token(x_api_token: str = Header(...)):
    if not x_api_token:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    token_hash = hashlib.sha256(x_api_token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            select(ApiToken.id, ApiToken.user_id).where(
                ApiToken.token_hash == token_hash,
                (ApiToken.expires_at.is_(None)) | (ApiToken.expires_at > func.now()),
            )
        )
        token = result.fetchone()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired API token")

    # Update last_used_at
    async with async_session() as session:
        await session.execute(update(ApiToken).where(ApiToken.id == token.id).values(last_used_at=func.now()))
        await session.commit()

    return {"user_id": token.user_id, "token_id": token.id}


# ── Rate limiter ──────────────────────────────────────────────────────

_RATE_LIMIT_REQUESTS = 10   # max requests per window
_RATE_LIMIT_WINDOW = 60     # window size in seconds


async def _check_rate_limit(token_id: int) -> None:
    """Redis-based sliding-window rate limiter scoped to a token per minute."""
    minute = int(time.time()) // _RATE_LIMIT_WINDOW
    key = f"ratelimit:ext:{token_id}:{minute}"
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _RATE_LIMIT_WINDOW)
    if count > _RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {_RATE_LIMIT_REQUESTS} requests per minute",
        )


# ── Status ────────────────────────────────────────────────────────────


@router.get("/status")
async def system_status(token_data: dict = Depends(verify_api_token)):
    """Returns basic system status and stats for external dashboards (e.g. Homepage)."""

    async with async_session() as session:
        gallery_count = (await session.execute(select(func.count()).select_from(Gallery))).scalar()
        image_count = (await session.execute(select(func.count()).select_from(Image))).scalar()
        tag_count = (await session.execute(select(func.count()).select_from(Tag))).scalar()
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
    }


# ── Galleries ─────────────────────────────────────────────────────────


@router.get("/galleries")
async def list_galleries(
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    source: str | None = Query(default=None),
    token_data: dict = Depends(verify_api_token),
):
    """List local library galleries (paginated)."""
    filters = []
    if source:
        filters.append(Gallery.source == source)

    async with async_session() as session:
        count_result = await session.execute(select(func.count()).select_from(Gallery).where(*filters))
        total = count_result.scalar() or 0

        data_query = select(Gallery).where(*filters).order_by(Gallery.added_at.desc()).limit(limit).offset(page * limit)
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
                "favorited": r.favorited,
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
        r = (await session.execute(select(Gallery).where(Gallery.id == gallery_id))).scalar_one_or_none()

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
        "favorited": r.favorited,
        "uploader": r.uploader,
        "download_status": r.download_status,
        "tags": r.tags_array or [],
    }


# ── Gallery images ────────────────────────────────────────────────────


@router.get("/galleries/{gallery_id}/images")
async def get_gallery_images(
    gallery_id: int,
    token_data: dict = Depends(verify_api_token),
):
    """List images for a gallery."""
    async with async_session() as session:
        # Verify gallery exists
        gallery = (await session.execute(select(Gallery.id).where(Gallery.id == gallery_id))).fetchone()
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        rows = (
            (await session.execute(select(Image).where(Image.gallery_id == gallery_id).order_by(Image.page_num)))
            .scalars()
            .all()
        )

    images = []
    for r in rows:
        images.append(
            {
                "id": r.id,
                "page_num": r.page_num,
                "filename": r.filename,
                "width": r.width,
                "height": r.height,
                "file_size": r.file_size,
                "media_type": r.media_type,
            }
        )

    return {"gallery_id": gallery_id, "images": images}


# ── Tags ──────────────────────────────────────────────────────────────


@router.get("/tags")
async def list_tags(
    prefix: str | None = Query(default=None),
    namespace: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    token_data: dict = Depends(verify_api_token),
):
    """List tags with optional filtering."""
    filters = []
    if prefix:
        filters.append(Tag.name.ilike(f"{prefix}%"))
    if namespace:
        filters.append(Tag.namespace == namespace)

    async with async_session() as session:
        count_result = await session.execute(select(func.count()).select_from(Tag).where(*filters))
        total = count_result.scalar() or 0

        rows = (
            (await session.execute(select(Tag).where(*filters).order_by(Tag.count.desc()).limit(limit).offset(offset)))
            .scalars()
            .all()
        )

    tags = [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows]
    return {"total": total, "tags": tags}


# ── Download trigger ──────────────────────────────────────────────────


@router.post("/download")
async def enqueue_download(
    url: str = Query(...),
    token_data: dict = Depends(verify_api_token),
):
    """Enqueue a download job via external API."""
    await _check_rate_limit(token_data["token_id"])
    job_id = _uuid.uuid4()

    async with async_session() as session:
        session.add(DownloadJob(id=job_id, url=url, status="queued"))
        await session.commit()

    return {"job_id": str(job_id), "status": "queued"}
