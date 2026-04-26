"""Thumbnail generation job for the worker package."""

import asyncio
import base64
import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Gallery, Image
from services.cas import resolve_blob_path, thumb_dir
from worker.constants import logger

THUMBNAIL_SIZES = (160, 360, 720)

_thumbnail_semaphore: asyncio.Semaphore | None = None
_thumbnail_semaphore_size: int | None = None


@dataclass(frozen=True, slots=True)
class _ThumbnailResult:
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    phash: str | None = None
    phash_int: int | None = None
    phash_q0: int | None = None
    phash_q1: int | None = None
    phash_q2: int | None = None
    phash_q3: int | None = None
    thumbhash: str | None = None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _thumbnail_workers() -> int:
    return _env_int("THUMBNAIL_WORKERS", 1)


def _thumbnail_commit_batch() -> int:
    return _env_int("THUMBNAIL_COMMIT_BATCH", 25)


def _get_thumbnail_semaphore() -> asyncio.Semaphore:
    global _thumbnail_semaphore, _thumbnail_semaphore_size

    size = _thumbnail_workers()
    if _thumbnail_semaphore is None or _thumbnail_semaphore_size != size:
        _thumbnail_semaphore = asyncio.Semaphore(size)
        _thumbnail_semaphore_size = size
    return _thumbnail_semaphore


async def _run_thumbnail_in_thread(*args) -> _ThumbnailResult | None:
    async with _get_thumbnail_semaphore():
        return await asyncio.to_thread(_generate_single_thumbnail_sync, *args)


def _unique_tmp_path(dest: Path) -> Path:
    suffix = f".{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    return dest.with_name(dest.name + suffix)


def _unique_video_frame_path(td: Path) -> Path:
    suffix = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
    return td / f"frame.{suffix}.jpg"


def _atomic_save_webp(image, dest: Path) -> None:
    tmp = _unique_tmp_path(dest)
    try:
        image.save(str(tmp), "WEBP", quality=85)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _encode_thumbhash(pil) -> str | None:
    try:
        import thumbhash as _thumbhash

        thumb_for_hash = pil.convert("RGBA")
        thumb_for_hash.thumbnail((100, 100))
        hash_value = _thumbhash.image_to_thumbhash(thumb_for_hash)
        if isinstance(hash_value, str):
            return hash_value
        return base64.b64encode(hash_value).decode()
    except Exception as exc:
        logger.warning("[thumbnail] thumbhash failed: %s", exc)
        return None


def _phash_parts(phash: str) -> dict[str, int]:
    phash_int_val = int(phash, 16)
    if phash_int_val >= (1 << 63):
        phash_int_val -= (1 << 64)

    def _to_signed16(v: int) -> int:
        return v - 0x10000 if v >= 0x8000 else v

    return {
        "phash_int": phash_int_val,
        "phash_q0": _to_signed16((phash_int_val >> 48) & 0xFFFF),
        "phash_q1": _to_signed16((phash_int_val >> 32) & 0xFFFF),
        "phash_q2": _to_signed16((phash_int_val >> 16) & 0xFFFF),
        "phash_q3": _to_signed16(phash_int_val & 0xFFFF),
    }


def _ffprobe_metadata(src: Path) -> dict:
    """Extract width, height, duration from video using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)

    # Find the video stream
    width, height, duration = None, None, None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0)) or None
            height = int(stream.get("height", 0)) or None
            break

    # Duration from format (more reliable)
    fmt = data.get("format", {})
    dur_str = fmt.get("duration")
    if dur_str:
        duration = float(dur_str)

    return {"width": width, "height": height, "duration": duration}


def _extract_video_frame(src: Path, output: Path, seek: float) -> None:
    """Extract a single frame from video at `seek` seconds as JPEG."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek),
        "-i", str(src),
        "-frames:v", "1",
        "-q:v", "2",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=True)


def _generate_single_thumbnail_sync(
    sha256: str,
    media_type: str,
    src: Path,
) -> _ThumbnailResult | None:
    """Generate thumbnails + hashes for one blob without touching the DB session."""
    from PIL import Image as PILImage

    if not src.exists():
        return None

    # Video files: extract metadata + thumbnail frame via ffmpeg
    if media_type == "video":
        td = thumb_dir(sha256)
        td.mkdir(parents=True, exist_ok=True)
        tmp_frame = _unique_video_frame_path(td)
        try:
            meta = _ffprobe_metadata(src)
            seek = min((meta["duration"] or 0) * 0.1, 1.0) if meta["duration"] else 0
            _extract_video_frame(src, tmp_frame, seek)

            with PILImage.open(tmp_frame) as pil:
                rgb = pil.convert("RGB")
                for size in THUMBNAIL_SIZES:
                    dest = td / f"thumb_{size}.webp"
                    if dest.exists():
                        continue
                    thumb = rgb.copy()
                    thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                    _atomic_save_webp(thumb, dest)

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
    td = thumb_dir(sha256)
    td.mkdir(parents=True, exist_ok=True)

    try:
        import imagehash

        with PILImage.open(src) as pil:
            phash = str(imagehash.phash(pil))
            phash_values = _phash_parts(phash)
            thumbhash = _encode_thumbhash(pil)

            rgb = pil.convert("RGB")
            for size in THUMBNAIL_SIZES:
                dest = td / f"thumb_{size}.webp"
                if dest.exists():
                    continue
                thumb = rgb.copy()
                thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                _atomic_save_webp(thumb, dest)

            return _ThumbnailResult(
                width=pil.size[0],
                height=pil.size[1],
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


def _apply_thumbnail_result(blob, result: _ThumbnailResult) -> None:
    blob.width = result.width
    blob.height = result.height
    blob.duration = result.duration
    if result.phash is not None:
        blob.phash = result.phash
        blob.phash_int = result.phash_int
        blob.phash_q0 = result.phash_q0
        blob.phash_q1 = result.phash_q1
        blob.phash_q2 = result.phash_q2
        blob.phash_q3 = result.phash_q3
    if result.thumbhash is not None:
        blob.thumbhash = result.thumbhash


def _cover_first(images: list[Image], cover_page: str) -> list[Image]:
    if not images:
        return []
    cover_index = len(images) - 1 if cover_page == "last" else 0
    cover = images[cover_index]
    return [cover, *(img for idx, img in enumerate(images) if idx != cover_index)]


async def _load_gallery_images(session, gallery_id: int) -> tuple[Gallery | None, list[Image]]:
    from sqlalchemy.orm import selectinload

    gallery = await session.get(Gallery, gallery_id)
    if not gallery:
        return None, []

    images = (
        await session.execute(
            select(Image)
            .where(Image.gallery_id == gallery_id)
            .order_by(Image.page_num.asc())
            .options(selectinload(Image.blob))
        )
    ).scalars().all()
    return gallery, list(images)


async def _process_images(session, images: list[Image], *, commit_batch: int) -> int:
    processed = 0
    pending: list[Image] = []

    for img in images:
        if img.blob:
            pending.append(img)
        if len(pending) >= commit_batch:
            processed += await _process_image_batch(session, pending)
            pending = []

    if pending:
        processed += await _process_image_batch(session, pending)

    return processed


async def _process_image_batch(session, images: list[Image]) -> int:
    work = [
        (img, resolve_blob_path(img.blob))
        for img in images
        if img.blob
    ]
    results = await asyncio.gather(
        *[
            _run_thumbnail_in_thread(img.blob.sha256, img.blob.media_type, src)
            for img, src in work
        ],
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


async def thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate 160/360/720px WebP thumbnails for all images in a gallery."""
    from core.source_display import get_display_config

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        gallery, images = await _load_gallery_images(session, gallery_id)
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
    from core.source_display import get_display_config

    logger.info("[thumbnail_cover] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        gallery, images = await _load_gallery_images(session, gallery_id)
        if gallery and images:
            display_cfg = get_display_config(gallery.source or "")
            cover = _cover_first(images, display_cfg.cover_page)[0]
            processed = await _process_images(session, [cover], commit_batch=1)

    logger.info("[thumbnail_cover] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}
