"""Canonical image ordering for gallery-dl social sources."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Gallery, Image, ReadProgress
from plugins.builtin.gallery_dl._sites import get_site_config

_POST_ID_RE = re.compile(r"^(\d+)")
_MEDIA_INDEX_RE = re.compile(r"_(\d+)$")


def is_social_source(source: str | None) -> bool:
    """Return whether a source should use newest-first social ordering."""
    if not source:
        return False
    return get_site_config(source).category == "social"


def parse_social_filename(filename: str | None) -> tuple[int, int] | None:
    """Extract ``(post_id, media_index)`` from a social filename.

    The post id must be the numeric run at the start of the filename stem.
    Media index is the trailing ``_N`` segment within the same post; missing
    index sorts as the first media item.
    """
    if not filename:
        return None
    stem = Path(filename).stem
    post_match = _POST_ID_RE.match(stem)
    if not post_match:
        return None
    media_match = _MEDIA_INDEX_RE.search(stem)
    media_index = int(media_match.group(1)) if media_match else 1
    return int(post_match.group(1)), media_index


def _timestamp_key(value: datetime | None) -> int:
    if value is None:
        return 0
    try:
        return int(value.timestamp() * 1_000_000)
    except OSError, OverflowError, ValueError:
        return 0


def social_image_sort_key(image: Any) -> tuple[int, int, int, int, int]:
    """Sort key for newest-first social image order."""
    parsed = parse_social_filename(getattr(image, "filename", None))
    stable_position = (
        getattr(image, "source_position", None) or getattr(image, "page_num", None) or getattr(image, "id", None) or 0
    )
    image_id = getattr(image, "id", None) or 0
    if parsed:
        post_id, media_index = parsed
        return (0, -post_id, media_index, stable_position, image_id)
    return (
        1,
        -_timestamp_key(getattr(image, "added_at", None)),
        stable_position,
        getattr(image, "page_num", None) or 0,
        image_id,
    )


async def reorder_social_gallery_images(
    session: AsyncSession,
    gallery_id: int,
    source: str | None,
) -> int:
    """Rebuild active page/source positions for a social gallery.

    Hidden images stay hidden. If a hidden image has a parseable social post id,
    its ``source_position`` is updated to the place it should occupy if restored.
    Read progress is retained and clamped to the new active page count.
    """
    if not is_social_source(source):
        return 0

    images = (
        (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id, Image.visibility.in_(("active", "user_hidden")))
                .order_by(Image.page_num.asc(), Image.id.asc())
            )
        )
        .scalars()
        .all()
    )
    active = [img for img in images if img.visibility == "active"]
    hidden = [img for img in images if img.visibility == "user_hidden"]
    ordered_active = sorted(active, key=social_image_sort_key)

    changed = 0
    if any(img.page_num != idx or img.source_position != idx for idx, img in enumerate(ordered_active, start=1)):
        for img in ordered_active:
            img.page_num = -int(img.id)
        await session.flush()

        for idx, img in enumerate(ordered_active, start=1):
            if img.page_num != idx:
                changed += 1
            img.page_num = idx
            img.source_position = idx
        await session.flush()

    active_keys = [social_image_sort_key(img) for img in ordered_active]
    for img in hidden:
        if parse_social_filename(img.filename) is None:
            continue
        key = social_image_sort_key(img)
        target_position = 1 + sum(1 for active_key in active_keys if active_key < key)
        if img.source_position != target_position:
            img.source_position = target_position
            changed += 1

    active_count = len(ordered_active)
    gallery = await session.get(Gallery, gallery_id)
    if gallery and gallery.pages != active_count:
        gallery.pages = active_count
        changed += 1

    await session.execute(
        update(ReadProgress)
        .where(ReadProgress.gallery_id == gallery_id, ReadProgress.last_page > active_count)
        .values(last_page=active_count)
    )
    return changed
