"""External API gallery image, page-file and tag endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter
from core.database import async_session
from db.models import Gallery, Image, Tag
from services.cas import image_file_url, resolve_blob_path
from services.cas import thumb_srcset as cas_thumb_srcset
from services.cas import thumb_url as cas_thumb_url
from services.external_auth import verify_api_token, verify_api_token_for_page_file

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Gallery images ────────────────────────────────────────────────────


@router.get("/galleries/{gallery_id}/images")
async def get_gallery_images(
    gallery_id: int,
    token_data: dict = Depends(verify_api_token),
):
    """List images for a gallery."""
    async with async_session() as session:
        # Verify gallery exists and is accessible
        gallery = (
            await session.execute(select(Gallery.id).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))
        ).fetchone()
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        rows = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id, Image.blob_sha256.is_not(None))
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
                # A link page's bytes stay in the user's folder; it has no CAS file.
                "file_url": image_file_url(blob, r.external_path),
                "thumb_url": cas_thumb_url(blob.sha256) if blob else None,
                "thumb_srcset": cas_thumb_srcset(blob.sha256) if blob else None,
            }
        )

    return {"gallery_id": gallery_id, "images": images}


@router.get("/galleries/{gallery_id}/images/{page_num}/file")
async def get_image_file(
    gallery_id: int,
    page_num: int,
    token_data: dict = Depends(verify_api_token_for_page_file),
):
    """Stream an image file for external readers (Mihon)."""
    async with async_session() as session:
        # Verify gallery is accessible before serving the image
        gallery_check = (
            await session.execute(select(Gallery.id).where(Gallery.id == gallery_id, gallery_access_filter(token_data)))
        ).fetchone()
        if not gallery_check:
            raise HTTPException(status_code=404, detail="Gallery not found")

        row = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id, Image.page_num == page_num)
                .options(selectinload(Image.blob))
            )
        ).scalar_one_or_none()

    if not row or (not row.blob and not row.external_path):
        raise HTTPException(status_code=404, detail="Image not found")

    # A pending link page has no blob yet; its own DB-recorded external_path
    # (never a request value) is the file to serve.
    file_path = resolve_blob_path(row.blob, row.external_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    ext_map = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".jxl": "image/jxl",
    }
    extension = row.blob.extension if row.blob else file_path.suffix
    content_type = ext_map.get(extension.lower(), "application/octet-stream")

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
