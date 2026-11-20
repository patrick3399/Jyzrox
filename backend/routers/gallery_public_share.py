"""Public share-link endpoints."""

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from db.models import (
    Blob,
    Gallery,
    GalleryShareLink,
    Image,
)
from services.cas import resolve_blob_path

router = APIRouter()
_member = require_role("member")


async def _share(db: AsyncSession, token: str) -> tuple[GalleryShareLink, Gallery]:
    row = (
        await db.execute(
            select(GalleryShareLink, Gallery)
            .join(Gallery, Gallery.id == GalleryShareLink.gallery_id)
            .where(
                GalleryShareLink.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                GalleryShareLink.revoked_at.is_(None),
                Gallery.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    link, gallery = row
    if link.expires_at is not None:
        expires_at = link.expires_at.replace(tzinfo=link.expires_at.tzinfo or UTC)
        if expires_at <= datetime.now(UTC):
            raise HTTPException(status_code=410, detail="Share link expired")
    return link, gallery


def _is_r18(tags: list[str]) -> bool:
    normalized = {tag.strip().lower() for tag in tags}
    return bool(normalized & {"r18", "rating:explicit", "rating:questionable", "content:r18"})


@router.get("/shares/{token}")
async def public_share(token: str, db: AsyncSession = Depends(get_db)):
    link, gallery = await _share(db, token)
    if link.filter_r18 and _is_r18(gallery.tags_array or []):
        raise HTTPException(status_code=451, detail="This shared gallery is hidden by the R18 content filter")
    images = (
        await db.execute(
            select(Image.id, Image.page_num)
            .where(Image.gallery_id == gallery.id, Image.visibility == "active")
            .order_by(Image.page_num)
        )
    ).all()
    return {
        "gallery": {
            "id": gallery.id,
            "title": gallery.title,
            "source": gallery.source,
            "source_id": gallery.source_id,
            "pages": len(images),
            "tags": [] if link.filter_r18 else gallery.tags_array or [],
        },
        "images": [
            {"id": image_id, "page_num": page_num, "url": f"/api/gallery-management/shares/{token}/images/{image_id}"}
            for image_id, page_num in images
        ],
    }


@router.get("/shares/{token}/images/{image_id}")
async def public_share_image(token: str, image_id: int, db: AsyncSession = Depends(get_db)):
    link, gallery = await _share(db, token)
    if link.filter_r18 and _is_r18(gallery.tags_array or []):
        raise HTTPException(status_code=451, detail="R18 content is filtered")
    row = (
        await db.execute(
            select(Image, Blob)
            .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.id == image_id, Image.gallery_id == gallery.id, Image.visibility == "active")
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")
    image, blob = row
    if blob is None and not image.external_path:
        raise HTTPException(status_code=404, detail="Image not found")
    # A pending link page has no blob: serve the row's own external_path.
    path = resolve_blob_path(blob, image.external_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(path, filename=image.filename or path.name, content_disposition_type="inline")
