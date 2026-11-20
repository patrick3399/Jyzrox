"""Library split from routers/library.py (library_serializers)."""

import re as _re

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.source_display import get_display_config
from db.models import (
    Blob,
    ExcludedBlob,
    Gallery,
    GallerySourceItem,
    Image,
)
from services.cas import (
    existing_base_thumbs,
    image_file_url,
)
from services.cas import thumb_srcset as cas_thumb_srcset
from services.cas import thumb_url as cas_thumb_url
from services.library_helpers import artist_display_name as _artist_display_name
from services.media_formats import media_type_for_extension


async def gallery_media_stats(db: AsyncSession, gallery_id: int) -> dict:
    """Total size and per-type counts over the pages the Reader would show."""
    excluded_sq = (
        select(ExcludedBlob.blob_sha256)
        .where(ExcludedBlob.gallery_id == gallery_id)
        .correlate(Image)
        .where(ExcludedBlob.blob_sha256 == Image.blob_sha256)
    )
    visible = (Image.gallery_id == gallery_id) & (Image.visibility == "active") & ~exists(excluded_sq)
    rows = (
        await db.execute(
            select(Blob.media_type, func.count(), func.coalesce(func.sum(Blob.file_size), 0))
            .select_from(Image)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(visible)
            .group_by(Blob.media_type)
        )
    ).all()
    counts = {"image": 0, "gif": 0, "video": 0}
    total_size = 0
    for media_type, count, size in rows:
        counts[media_type if media_type in counts else "image"] += count
        total_size += int(size)
    # Link-mode pages not hashed yet have no blob: classify by name, size by stat.
    pending = (await db.execute(select(Image).where(visible).where(Image.blob_sha256.is_(None)))).scalars().all()
    for img in pending:
        kind = _pending_media_type(img)
        counts[kind if kind in counts else "image"] += 1
        total_size += int(img.source_size or 0)
    return {
        "total_size": total_size,
        "image_count": counts["image"],
        "gif_count": counts["gif"],
        "video_count": counts["video"],
    }


def is_pending(img: Image) -> bool:
    """True for a link page that is registered but not hashed yet."""
    return img.blob_sha256 is None and img.external_path is not None


def pending_media_type(img: Image) -> str:
    """Media type of a page without a blob, derived from its file extension."""
    return media_type_for_extension(img.filename or img.external_path or "") or "image"


def media_type(img: Image) -> str:
    blob = img.blob
    return blob.media_type if blob else _pending_media_type(img)


def file_size(img: Image) -> int | None:
    blob = img.blob
    return blob.file_size if blob else img.source_size


def thumb_fields(blob, thumbs: set[str]) -> dict:
    """Return a blob's thumbnail URLs, or None when its base thumb is missing.

    ``thumbs`` comes from ``existing_base_thumbs`` for the whole response, so
    serializing a page does no filesystem I/O.
    """
    if blob is None or blob.sha256 not in thumbs:
        return {"thumb_path": None, "thumb_srcset": None}
    return {"thumb_path": cas_thumb_url(blob.sha256), "thumb_srcset": cas_thumb_srcset(blob.sha256)}


def serialize_gallery(
    g: Gallery,
    cover_thumb: str | None = None,
    is_favorited: bool = False,
    my_rating: int | None = None,
    in_reading_list: bool = False,
) -> dict:
    display_cfg = get_display_config(g.source or "")
    return {
        "id": g.id,
        "source": g.source,
        "source_id": g.source_id,
        "title": g.title,
        "title_jpn": g.title_jpn,
        "category": g.category,
        "language": g.language,
        "pages": g.pages,
        "source_pages": g.source_pages,
        "missing_pages": (max(g.source_pages - (g.pages or 0), 0) if g.source_pages is not None else None),
        "posted_at": g.posted_at.isoformat() if g.posted_at else None,
        "added_at": g.added_at.isoformat() if g.added_at else None,
        "content_updated_at": g.content_updated_at.isoformat() if g.content_updated_at else None,
        "rating": g.rating,
        "favorited": False,
        "is_favorited": is_favorited,
        "my_rating": my_rating,
        "in_reading_list": in_reading_list,
        "uploader": g.uploader,
        "artist_id": g.artist_id,
        "artist_name": _artist_display_name(g.artist_id, g.uploader),
        "download_status": g.download_status,
        "import_mode": g.import_mode,
        "tags_array": g.tags_array or [],
        "cover_thumb": cover_thumb,
        "source_url": g.source_url,
        "source_path": g.source_path,
        "display_order": display_cfg.image_order,
        "metadata_updated_at": g.metadata_updated_at.isoformat() if g.metadata_updated_at else None,
    }


def serialize_image(img: Image, thumbs: set[str]) -> dict:
    blob = img.blob
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "filename": img.filename,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        "file_path": image_file_url(blob, img.external_path),
        **_thumb_fields(blob, thumbs),
        "file_size": _file_size(img),
        "file_hash": blob.sha256 if blob else None,
        "media_type": _media_type(img),
        "duration": blob.duration if blob else None,
        "thumbhash": blob.thumbhash if blob else None,
        "pending": _is_pending(img),
        "visibility": img.visibility,
        "source_item_id": img.source_item_id,
        "source_item_url": img.source_item_url,
        "source_position": img.source_position,
        "source_seen_at": img.source_seen_at.isoformat() if img.source_seen_at else None,
        "hidden_at": img.hidden_at.isoformat() if img.hidden_at else None,
    }


def source_item_dict(item: GallerySourceItem) -> dict:
    return {
        "id": item.id,
        "source_item_id": item.source_item_id,
        "source_item_url": item.source_item_url,
        "title": item.title,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "page_count": item.page_count,
        "position": item.source_position,
        "status": item.status,
        "metadata": item.metadata_json or {},
    }


async def images_with_source_items(db: AsyncSession, images: list[Image]) -> list[dict]:
    row_ids = {img.source_item_row_id for img in images if img.source_item_row_id}
    item_map = {}
    if row_ids:
        items = (await db.execute(select(GallerySourceItem).where(GallerySourceItem.id.in_(row_ids)))).scalars().all()
        item_map = {item.id: item for item in items}
    thumbs = await existing_base_thumbs(image.blob_sha256 for image in images)
    result = []
    for image in images:
        data = _i(image, thumbs)
        item = item_map.get(image.source_item_row_id)
        if item:
            match = _re.search(r":p(\d+)$", image.source_item_id or "")
            data["source_work"] = _source_item_dict(item)
            data["source_work_page"] = int(match.group(1)) if match else None
        result.append(data)
    return result


_is_pending = is_pending
_pending_media_type = pending_media_type
_media_type = media_type
_file_size = file_size
_thumb_fields = thumb_fields
_i = serialize_image
_source_item_dict = source_item_dict
