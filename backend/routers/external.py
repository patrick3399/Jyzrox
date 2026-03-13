"""External API endpoints for third-party integrations."""

import hashlib
import logging
import shutil
import time
import uuid as _uuid

import psutil
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text, update

from core.auth import gallery_access_filter
from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from core.utils import detect_source
from db.models import ApiToken, Blob, DownloadJob, Gallery, Image, Tag
from services.cas import cas_url, thumb_url as cas_thumb_url, resolve_blob_path
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


async def _require_external_api_enabled():
    """Raise 404 if External API feature is disabled."""
    val = await get_redis().get("setting:external_api_enabled")
    if val is not None:
        enabled = val == b"1"
    else:
        enabled = settings.external_api_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="External API is disabled")


router = APIRouter(tags=["external"], dependencies=[Depends(_require_external_api_enabled)])


async def verify_api_token(x_api_token: str = Header(...)):
    if not x_api_token:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    token_hash = hashlib.sha256(x_api_token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            text(
                "SELECT t.id, t.user_id, u.role "
                "FROM api_tokens t JOIN users u ON t.user_id = u.id "
                "WHERE t.token_hash = :hash AND (t.expires_at IS NULL OR t.expires_at > now())"
            ),
            {"hash": token_hash},
        )
        token = result.fetchone()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired API token")

    # Update last_used_at
    async with async_session() as session:
        await session.execute(update(ApiToken).where(ApiToken.id == token.id).values(last_used_at=func.now()))
        await session.commit()

    return {"user_id": token.user_id, "token_id": token.id, "role": token.role or "viewer"}


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
        # Fast estimated counts via pg_stat (< 1ms vs 2-5s for COUNT(*) on large tables)
        row_estimates = (await session.execute(text(
            "SELECT relname, n_live_tup::bigint FROM pg_stat_user_tables "
            "WHERE relname IN ('galleries', 'images', 'tags')"
        ))).all()
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
        import subprocess
        proc = await _asyncio.create_subprocess_exec(
            "df", "-i", "--output=itotal,iused,iavail,ipcent", settings.data_cas_path,
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
                Gallery.id.in_(
                    select(UserFavorite.gallery_id).where(UserFavorite.user_id == token_data["user_id"])
                )
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
        count_result = await session.execute(select(func.count()).select_from(Gallery).where(*filters, gallery_access_filter(token_data)))
        total = count_result.scalar() or 0

        data_query = select(Gallery).where(*filters, gallery_access_filter(token_data)).order_by(Gallery.added_at.desc()).limit(limit).offset(page * limit)
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
        r = (await session.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))).scalar_one_or_none()

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


# ── Gallery images ────────────────────────────────────────────────────


@router.get("/galleries/{gallery_id}/images")
async def get_gallery_images(
    gallery_id: int,
    token_data: dict = Depends(verify_api_token),
):
    """List images for a gallery."""
    async with async_session() as session:
        # Verify gallery exists and is accessible
        gallery = (await session.execute(select(Gallery.id).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))).fetchone()
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        rows = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.desc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

    images = []
    for r in rows:
        blob = r.blob
        images.append(
            {
                "id": r.id,
                "page_num": r.page_num,
                "filename": r.filename,
                "width": blob.width if blob else None,
                "height": blob.height if blob else None,
                "file_size": blob.file_size if blob else None,
                "media_type": blob.media_type if blob else None,
                "duration": blob.duration if blob else None,
                "file_url": cas_url(blob.sha256, blob.extension) if blob else None,
                "thumb_url": cas_thumb_url(blob.sha256) if blob else None,
            }
        )

    return {"gallery_id": gallery_id, "images": images}


@router.get("/galleries/{gallery_id}/images/{page_num}/file")
async def get_image_file(
    gallery_id: int,
    page_num: int,
    token_data: dict = Depends(verify_api_token),
):
    """Stream an image file for external readers (Mihon)."""
    async with async_session() as session:
        # Verify gallery is accessible before serving the image
        gallery_check = (await session.execute(select(Gallery.id).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))).fetchone()
        if not gallery_check:
            raise HTTPException(status_code=404, detail="Gallery not found")

        row = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id, Image.page_num == page_num)
                .options(selectinload(Image.blob))
            )
        ).scalar_one_or_none()

    if not row or not row.blob:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = resolve_blob_path(row.blob)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    ext_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".avif": "image/avif",
    }
    content_type = ext_map.get(row.blob.extension.lower(), "application/octet-stream")

    from fastapi.responses import FileResponse
    return FileResponse(str(file_path), media_type=content_type)


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


class ExternalDownloadRequest(BaseModel):
    url: str


@router.post("/download")
async def enqueue_download(
    request: Request,
    body: ExternalDownloadRequest | None = None,
    url: str | None = Query(default=None),
    token_data: dict = Depends(verify_api_token),
):
    """Enqueue a download job via external API.

    Accepts the target URL either as a JSON body field ``url`` or as a query
    parameter ``url``.  JSON body takes priority; if both are absent a 422 is
    returned.

    Order: ARQ enqueue first, then DB commit. If ARQ fails we never create the
    DB record. If DB insert fails after a successful ARQ enqueue we log a
    warning — the ARQ job will time out naturally without a matching DB record.
    """
    resolved_url = (body.url if body else None) or url
    if not resolved_url:
        raise HTTPException(status_code=422, detail="Missing 'url' in body or query parameter")

    # Viewers cannot trigger downloads
    from core.auth import ROLE_HIERARCHY
    if ROLE_HIERARCHY.get(token_data.get("role", ""), 0) < ROLE_HIERARCHY["member"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions: member role required")

    await _check_rate_limit(token_data["token_id"])
    job_id = _uuid.uuid4()
    source = detect_source(resolved_url)

    # 1. Enqueue ARQ job first — if this fails, no DB record is created.
    arq = request.app.state.arq
    try:
        await arq.enqueue_job(
            "download_job",
            resolved_url,
            source,
            None,   # options
            str(job_id),
            None,   # total
            _job_id=str(job_id),
        )
    except Exception as exc:
        logger.error("[external/enqueue] ARQ enqueue failed: %s", exc)
        raise HTTPException(status_code=503, detail="Failed to enqueue download job")

    # 2. Persist DB record. If this fails, log a warning; the ARQ job will
    #    eventually time out without a matching DB row.
    try:
        async with async_session() as session:
            session.add(DownloadJob(id=job_id, url=resolved_url, source=source, status="queued", user_id=token_data["user_id"]))
            await session.commit()
    except Exception as exc:
        logger.warning(
            "[external/enqueue] ARQ job %s enqueued but DB insert failed: %s — job will time out naturally",
            job_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Job enqueued but failed to persist to database")

    return {"job_id": str(job_id), "status": "queued"}
