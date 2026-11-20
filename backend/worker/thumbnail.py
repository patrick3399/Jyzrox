"""Thumbnail generation job for the worker package."""

import asyncio
import json
import subprocess
import zipfile
from pathlib import Path

from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from core.gallery_helpers import select_cover_image
from db.models import Gallery, Image
from services.cas import (
    THUMBNAIL_SIZES,
    resolve_blob_path,
    thumb_dir,
    thumbnails_complete_at,
)
from services.image_codecs import register_image_codecs
from worker.constants import logger
from worker.thumbnail_apply import _apply_thumbnail_result as _apply_thumbnail_result
from worker.thumbnail_apply import _cover_first as _cover_first
from worker.thumbnail_media import (
    _atomic_save_webp,
    _current_thumbnail_version,
    _downscale_to_width,
    _encode_thumbhash,
    _ensure_preview,
    _extract_video_frame,
    _ffprobe_metadata,
    _phash_parts,
    _resize_width_tier,
    _unique_video_frame_path,
    _write_thumbnail_version,
)
from worker.thumbnail_media import (
    _generate_zip_preview as _generate_zip_preview,
)
from worker.thumbnail_pool import (
    _PRIORITY_BULK,
    _PRIORITY_COVER,
    _get_thumbnail_executor,
    _get_thumbnail_semaphore,
    _thumbnail_commit_batch,
    _ThumbnailResult,
)

try:
    from PIL import Image as _PILImage

    # Pillow warns above this threshold and raises DecompressionBombError above
    # twice the threshold. Keep a finite cap while allowing high-resolution
    # source images up to the resulting 400 MP hard-error boundary.
    _PILImage.MAX_IMAGE_PIXELS = 200_000_000  # edge case #110: decompression bomb cap
except ImportError:
    pass

register_image_codecs()


async def _run_thumbnail_in_thread(*args, priority: int = _PRIORITY_BULK) -> _ThumbnailResult | None:
    semaphore = _get_thumbnail_semaphore()
    await semaphore.acquire(priority)
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_get_thumbnail_executor(), _generate_single_thumbnail_sync, *args)
    finally:
        semaphore.release()


def _generate_single_thumbnail_sync(
    sha256: str,
    media_type: str,
    src: Path,
) -> _ThumbnailResult | None:
    """Generate thumbnails + hashes for one blob without touching the DB session."""
    from PIL import Image as PILImage

    if not src.exists():
        return None

    td = thumb_dir(sha256)
    td.mkdir(parents=True, exist_ok=True)
    current_version = _current_thumbnail_version(td)
    is_zip_animation = zipfile.is_zipfile(src)
    if media_type == "video" or src.suffix.lower() == ".gif" or is_zip_animation:
        preview = _ensure_preview(src, td)
        if is_zip_animation and preview is not None:
            src = preview
            media_type = "video"

    # Video files: extract metadata + thumbnail frame via ffmpeg
    if media_type == "video":
        tmp_frame = _unique_video_frame_path(td)
        try:
            meta = _ffprobe_metadata(src)
            seek = min((meta["duration"] or 0) * 0.1, 1.0) if meta["duration"] else 0
            _extract_video_frame(src, tmp_frame, seek)

            with PILImage.open(tmp_frame) as pil:
                rgb = pil.convert("RGB")
                wrote_thumbnail = False
                for size in THUMBNAIL_SIZES:
                    dest = td / f"thumb_{size}.webp"
                    if current_version and dest.exists():
                        continue
                    thumb = _resize_width_tier(rgb, size)
                    _atomic_save_webp(thumb, dest)
                    wrote_thumbnail = True
                if wrote_thumbnail or not current_version:
                    _write_thumbnail_version(td)

                return _ThumbnailResult(
                    width=meta["width"],
                    height=meta["height"],
                    duration=meta["duration"],
                    thumbhash=_encode_thumbhash(pil),
                )
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError, ValueError) as exc:
            logger.error("[thumbnail] video %s: %s", src, exc)
            return None
        finally:
            tmp_frame.unlink(missing_ok=True)

    # Image files
    try:
        import imagehash
        from PIL import ImageOps

        with PILImage.open(src) as source_image:
            # in_place skips exif_transpose's full-resolution image.copy() on
            # the common path where there is no orientation tag to apply.
            ImageOps.exif_transpose(source_image, in_place=True)
            source_size = source_image.size

            # phash stays at source resolution: it feeds dedup Tier-1, so
            # existing rows must stay comparable. It converts to mode "L"
            # (1 byte/px), the cheapest of the full-size derivations.
            phash = str(imagehash.phash(source_image))
            phash_values = _phash_parts(phash)

            # Everything below needs at most the largest tier, so derive it
            # once. A 3-4 byte/px buffer at source resolution costs 300-400 MB
            # for a 100 MP image, and two of those concurrently is what
            # OOM-killed the 2 GB worker container (2026-08-13).
            base = _downscale_to_width(source_image, max(THUMBNAIL_SIZES))
            thumbhash = _encode_thumbhash(base)

            rgb = base.convert("RGB")
            wrote_thumbnail = False
            for size in THUMBNAIL_SIZES:
                dest = td / f"thumb_{size}.webp"
                if current_version and dest.exists():
                    continue
                thumb = _resize_width_tier(rgb, size)
                _atomic_save_webp(thumb, dest)
                wrote_thumbnail = True
            if wrote_thumbnail or not current_version:
                _write_thumbnail_version(td)

            return _ThumbnailResult(
                width=source_size[0],
                height=source_size[1],
                phash=phash,
                thumbhash=thumbhash,
                **phash_values,
            )

    except (OSError, ValueError) as exc:
        logger.error("[thumbnail] %s: %s", src, exc)
        return None


async def generate_single_thumbnail(blob, src: Path, session=None) -> bool:
    """Generate thumbnails + metadata for a single blob and apply results to it."""
    result = await _run_thumbnail_in_thread(blob.sha256, blob.media_type, src)
    if result is None:
        return False
    _apply_thumbnail_result(blob, result)
    return True


def _blob_needs_thumbnail(blob) -> bool:
    if blob is None:
        return False
    if not thumbnails_complete_at(thumb_dir(blob.sha256)):
        return True
    if blob.width is None or blob.height is None or blob.thumbhash is None:
        return True
    return blob.media_type != "video" and blob.phash is None


async def _load_gallery_images(
    session, gallery_id: int, image_ids: list[int] | None = None
) -> tuple[Gallery | None, list[Image]]:
    from sqlalchemy.orm import selectinload

    gallery = await session.get(Gallery, gallery_id)
    if not gallery:
        return None, []

    stmt = select(Image).where(Image.gallery_id == gallery_id)
    if image_ids is not None:
        stmt = stmt.where(Image.id.in_(image_ids))
    images = (
        (await session.execute(stmt.order_by(Image.page_num.asc()).options(selectinload(Image.blob)))).scalars().all()
    )
    return gallery, list(images)


async def _process_images(session, images: list[Image], *, commit_batch: int, priority: int = _PRIORITY_BULK) -> int:
    processed = 0
    pending: list[Image] = []

    for img in images:
        if img.blob:
            pending.append(img)
        if len(pending) >= commit_batch:
            processed += await _process_image_batch(session, pending, priority)
            pending = []

    if pending:
        processed += await _process_image_batch(session, pending, priority)

    return processed


async def _process_image_batch(session, images: list[Image], priority: int = _PRIORITY_BULK) -> int:
    work = [(img, resolve_blob_path(img.blob, img.external_path)) for img in images if _blob_needs_thumbnail(img.blob)]
    if not work:
        return 0

    results = await asyncio.gather(
        *[_run_thumbnail_in_thread(img.blob.sha256, img.blob.media_type, src, priority=priority) for img, src in work],
        return_exceptions=True,
    )

    processed = 0
    for (img, src), result in zip(work, results, strict=False):
        if isinstance(result, Exception):
            logger.error("[thumbnail] %s: %s", src, result)
            continue
        if result is None:
            continue
        _apply_thumbnail_result(img.blob, result)
        processed += 1

    await session.commit()
    return processed


async def thumbnail_job(ctx: dict, gallery_id: int, image_ids: list[int] | None = None) -> dict:
    """Generate 160/360/720px WebP thumbnails for a gallery's images.

    `image_ids` limits the job to those images. A download publishes its pages
    in batches this way, so thumbnails appear while it is still running and a
    batch never rescans the whole gallery.
    """
    from core.source_display import get_display_config

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        gallery, images = await _load_gallery_images(session, gallery_id, image_ids)
        if gallery:
            display_cfg = get_display_config(gallery.source or "")
            ordered_images = _cover_first(images, display_cfg.cover_page)
            processed = await _process_images(session, ordered_images, commit_batch=_thumbnail_commit_batch())

    logger.info("[thumbnail] gallery_id=%d: %d done", gallery_id, processed)

    from core.events import EventType, emit_safe

    await emit_safe(EventType.THUMBNAILS_GENERATED, resource_type="gallery", resource_id=gallery_id, count=processed)

    return {"status": "done", "processed": processed}


async def cover_thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate thumbnails only for the configured cover image of a gallery."""
    logger.info("[thumbnail_cover] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if gallery:
            cover = await select_cover_image(session, gallery_id, gallery.source or "")
            if cover:
                processed = await _process_images(session, [cover], commit_batch=1, priority=_PRIORITY_COVER)

    logger.info("[thumbnail_cover] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}
