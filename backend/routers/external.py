"""External API endpoints for third-party integrations."""

import hashlib
import shutil

import psutil
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import text

from core.config import settings
from core.database import async_session

router = APIRouter(tags=["external"])


async def verify_api_token(x_api_token: str = Header(...)):
    if not x_api_token:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    token_hash = hashlib.sha256(x_api_token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, user_id FROM api_tokens WHERE token_hash = :th AND (expires_at IS NULL OR expires_at > now())"),
            {"th": token_hash},
        )
        token = result.fetchone()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired API token")

    # Update last_used_at
    async with async_session() as session:
        await session.execute(
            text("UPDATE api_tokens SET last_used_at = now() WHERE id = :id"),
            {"id": token.id},
        )
        await session.commit()

    return {"user_id": token.user_id, "token_id": token.id}


# ── Status ────────────────────────────────────────────────────────────

@router.get("/status")
async def system_status(token_data: dict = Depends(verify_api_token)):
    """Returns basic system status and stats for external dashboards (e.g. Homepage)."""

    async with async_session() as session:
        counts = await session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM galleries) as gallery_count,
                (SELECT COUNT(*) FROM images) as image_count,
                (SELECT COUNT(*) FROM tags) as tag_count,
                (SELECT COUNT(*) FROM download_jobs WHERE status IN ('queued', 'running')) as active_downloads
        """))
        stats = counts.fetchone()

    try:
        usage = shutil.disk_usage(settings.data_gallery_path)
        disk_total = usage.total
        disk_free = usage.free
    except OSError:
        disk_total = 0
        disk_free = 0

    return {
        "status": "online",
        "version": "2.0.0",
        "stats": {
            "galleries": stats.gallery_count,
            "images": stats.image_count,
            "tags": stats.tag_count,
            "active_downloads": stats.active_downloads,
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
    async with async_session() as session:
        where = "WHERE source = :source" if source else ""
        params: dict = {"limit": limit, "offset": page * limit}
        if source:
            params["source"] = source

        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM galleries {where}"), params
        )
        total = count_result.scalar() or 0

        rows = await session.execute(
            text(f"""
                SELECT id, source, source_id, title, title_jpn, category, language,
                       pages, posted_at, added_at, rating, favorited, uploader,
                       download_status, tags_array
                FROM galleries {where}
                ORDER BY added_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

    galleries = []
    for r in rows:
        galleries.append({
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
        })

    return {"total": total, "page": page, "galleries": galleries}


@router.get("/galleries/{gallery_id}")
async def get_gallery(
    gallery_id: int,
    token_data: dict = Depends(verify_api_token),
):
    """Get a single gallery by ID."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT id, source, source_id, title, title_jpn, category, language,
                       pages, posted_at, added_at, rating, favorited, uploader,
                       download_status, tags_array
                FROM galleries WHERE id = :id
            """),
            {"id": gallery_id},
        )
        r = result.fetchone()

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
        gcheck = await session.execute(
            text("SELECT id FROM galleries WHERE id = :id"), {"id": gallery_id}
        )
        if not gcheck.fetchone():
            raise HTTPException(status_code=404, detail="Gallery not found")

        rows = await session.execute(
            text("""
                SELECT id, page_num, filename, width, height, file_size, media_type
                FROM images WHERE gallery_id = :gid ORDER BY page_num
            """),
            {"gid": gallery_id},
        )

    images = []
    for r in rows:
        images.append({
            "id": r.id,
            "page_num": r.page_num,
            "filename": r.filename,
            "width": r.width,
            "height": r.height,
            "file_size": r.file_size,
            "media_type": r.media_type,
        })

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
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if prefix:
        conditions.append("name ILIKE :prefix")
        params["prefix"] = f"{prefix}%"
    if namespace:
        conditions.append("namespace = :namespace")
        params["namespace"] = namespace

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with async_session() as session:
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM tags {where}"), params
        )
        total = count_result.scalar() or 0

        rows = await session.execute(
            text(f"""
                SELECT id, namespace, name, count FROM tags {where}
                ORDER BY count DESC LIMIT :limit OFFSET :offset
            """),
            params,
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
    import uuid as _uuid
    job_id = str(_uuid.uuid4())

    async with async_session() as session:
        await session.execute(
            text("INSERT INTO download_jobs (id, url, status) VALUES (:id, :url, 'queued')"),
            {"id": job_id, "url": url},
        )
        await session.commit()

    return {"job_id": job_id, "status": "queued"}
