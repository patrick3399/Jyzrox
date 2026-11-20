"""Library split from routers/library.py (library_images_hide)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_role
from core.database import get_db
from db.models import (
    Gallery,
    Image,
)
from services.library_helpers import check_write_access as _check_write_access
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source
from services.library_image_visibility import active_image_count as _active_image_count
from services.library_image_visibility import hide_image_row as _hide_image_row
from services.library_image_visibility import hide_image_rows as _hide_image_rows
from services.library_image_visibility import restore_image_row as _restore_image_row

_member = require_role("member")
router = APIRouter()


class DeleteImageBody(BaseModel):
    page_num: int


@router.post("/galleries/{source}/{source_id}/delete-image", deprecated=True)
async def delete_gallery_image(
    source: str,
    source_id: str,
    body: DeleteImageBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Hide a single image from a gallery by page number.

    This legacy endpoint used to delete the Image row and block the blob from
    re-import. It now preserves local data and marks the image as user_hidden
    so accidental hides can be restored immediately.
    """

    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = gallery.id
    _check_write_access(auth, gallery)

    img_stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id, Image.page_num == body.page_num, Image.visibility == "active")
        .options(selectinload(Image.blob))
    )
    img = (await db.execute(img_stmt)).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")

    remaining_pages = await _hide_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "action": "hidden", "remaining_pages": remaining_pages}


@router.post("/images/{image_id}/hide")
async def hide_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Hide an image without deleting local data."""
    img = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
            .options(selectinload(Image.gallery))
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    gallery = img.gallery
    _check_write_access(auth, gallery)
    remaining_pages = await _hide_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "remaining_pages": remaining_pages}


@router.post("/images/{image_id}/restore")
async def restore_hidden_image(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore a user-hidden image immediately."""
    img = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
            .options(selectinload(Image.gallery))
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    gallery = img.gallery
    _check_write_access(auth, gallery)
    remaining_pages = await _restore_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "remaining_pages": remaining_pages}


class ImageIdsBody(BaseModel):
    image_ids: list[int] = Field(min_length=1, max_length=1000)


@router.post("/galleries/{source}/{source_id}/images/hide-batch")
async def hide_images_batch(
    source: str,
    source_id: str,
    body: ImageIdsBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Hide multiple images in one transaction with a single page compaction.

    Ids that are not active images of this gallery are silently skipped so the
    client can retry a stale selection without errors.
    """
    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    _check_write_access(auth, gallery)

    images = (
        (
            await db.execute(
                select(Image).where(
                    Image.gallery_id == gallery.id,
                    Image.id.in_(body.image_ids),
                    Image.visibility == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    remaining_pages = await _hide_image_rows(db, gallery, list(images))
    await db.commit()
    return {"status": "ok", "hidden": len(images), "remaining_pages": remaining_pages}


@router.post("/galleries/{source}/{source_id}/images/restore-batch")
async def restore_images_batch(
    source: str,
    source_id: str,
    body: ImageIdsBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore multiple user-hidden images (undo of a batch hide).

    Images are restored in ascending source-position order so each one lands
    at its original page like sequential single restores would.
    """
    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    _check_write_access(auth, gallery)

    images = (
        (
            await db.execute(
                select(Image).where(
                    Image.gallery_id == gallery.id,
                    Image.id.in_(body.image_ids),
                    Image.visibility == "user_hidden",
                )
            )
        )
        .scalars()
        .all()
    )
    ordered = sorted(
        images,
        key=lambda img: (img.source_position is None, img.source_position or 0, img.id),
    )
    remaining_pages = await _active_image_count(db, gallery.id)
    for img in ordered:
        remaining_pages = await _restore_image_row(db, gallery, img)
    await db.commit()
    return {"status": "ok", "restored": len(images), "remaining_pages": remaining_pages}
