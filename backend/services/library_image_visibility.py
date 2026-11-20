"""Library split from routers/library.py (library_image_visibility)."""

from datetime import UTC, datetime

from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Gallery,
    Image,
)


async def active_image_count(db: AsyncSession, gallery_id: int) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Image).where(Image.gallery_id == gallery_id, Image.visibility == "active")
        )
    ).scalar_one()


async def compact_active_image_pages(db: AsyncSession, gallery_id: int) -> int:
    images = (
        (
            await db.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id, Image.visibility == "active")
                .order_by(asc(Image.page_num), asc(Image.id))
            )
        )
        .scalars()
        .all()
    )
    if all(img.page_num == index for index, img in enumerate(images, start=1)):
        return len(images)

    for img in images:
        img.page_num = -int(img.id)
    await db.flush()

    for index, img in enumerate(images, start=1):
        img.page_num = index
    await db.flush()
    return len(images)


async def hide_image_rows(db: AsyncSession, gallery: Gallery, images: list[Image]) -> int:
    """Mark images user_hidden with a single page compaction at the end."""
    to_hide = [img for img in images if img.visibility == "active"]
    hidden_at = datetime.now(UTC)
    for img in to_hide:
        if img.source_position is None:
            img.source_position = img.page_num
        img.visibility = "user_hidden"
        img.hidden_at = hidden_at
        img.page_num = -int(img.id)
    if to_hide:
        await db.flush()
    active_count = await _compact_active_image_pages(db, gallery.id)
    gallery.pages = active_count
    return active_count


async def hide_image_row(db: AsyncSession, gallery: Gallery, img: Image) -> int:
    if img.visibility != "active":
        return await _active_image_count(db, gallery.id)
    return await _hide_image_rows(db, gallery, [img])


async def restore_image_row(db: AsyncSession, gallery: Gallery, img: Image) -> int:
    if img.visibility != "user_hidden":
        return await _active_image_count(db, gallery.id)

    active_images = (
        (
            await db.execute(
                select(Image)
                .where(Image.gallery_id == gallery.id, Image.visibility == "active")
                .order_by(asc(Image.page_num), asc(Image.id))
            )
        )
        .scalars()
        .all()
    )
    if img.source_position is None:
        target_page = len(active_images) + 1
    else:
        target_page = 1 + sum(
            1
            for active in active_images
            if (active.source_position if active.source_position is not None else active.page_num) < img.source_position
        )

    moving_images = [(active, active.page_num) for active in active_images if active.page_num >= target_page]
    for active, _old_page in moving_images:
        active.page_num = -int(active.id)
    await db.flush()

    for active, old_page in moving_images:
        active.page_num = old_page + 1
    img.page_num = target_page
    img.visibility = "active"
    img.hidden_at = None
    await db.flush()

    active_count = len(active_images) + 1
    gallery.pages = active_count
    return active_count


_active_image_count = active_image_count
_compact_active_image_pages = compact_active_image_pages
_hide_image_rows = hide_image_rows
