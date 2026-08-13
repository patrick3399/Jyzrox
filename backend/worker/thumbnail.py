"""Thumbnail generation job for the worker package."""

import asyncio
import json
import os
import subprocess
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from core.gallery_helpers import select_cover_image
from db.models import Gallery, Image
from services.cas import (
    THUMBNAIL_SIZES,
    THUMBNAIL_VERSION,
    THUMBNAIL_VERSION_FILENAME,
    resolve_blob_path,
    thumb_dir,
    thumbnails_complete_at,
)
from worker.constants import logger
from worker.helpers import env_int
from worker.thumbhash_utils import encode_pil_thumbhash

try:
    from PIL import Image as _PILImage

    # Pillow warns above this threshold and raises DecompressionBombError above
    # twice the threshold. Keep a finite cap while allowing high-resolution
    # source images up to the resulting 400 MP hard-error boundary.
    _PILImage.MAX_IMAGE_PIXELS = 200_000_000  # edge case #110: decompression bomb cap
except ImportError:
    pass

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


def _thumbnail_workers() -> int:
    return env_int("THUMBNAIL_WORKERS", 1)


def _thumbnail_commit_batch() -> int:
    return env_int("THUMBNAIL_COMMIT_BATCH", 25)


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


def _current_thumbnail_version(td: Path) -> bool:
    try:
        return int((td / THUMBNAIL_VERSION_FILENAME).read_text(encoding="ascii").strip()) == THUMBNAIL_VERSION
    except OSError, ValueError:
        return False


def _write_thumbnail_version(td: Path) -> None:
    destination = td / THUMBNAIL_VERSION_FILENAME
    temporary = _unique_tmp_path(destination)
    try:
        temporary.write_text(str(THUMBNAIL_VERSION), encoding="ascii")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _downscale_to_width(image, size: int):
    """Return `image` no wider than `size`, allocating only the destination.

    `Image.thumbnail()` mutates in place, so a caller has to copy first — at
    source resolution that copy is one of the largest allocations in the
    pipeline (300 MB for a 100 MP source). `resize()` allocates the
    destination only.
    """
    width, height = image.size
    if width <= size:
        return image.copy()
    target_height = max(1, round(height * size / width))
    return image.resize((size, target_height), _PILImage.Resampling.LANCZOS)


def _resize_width_tier(image, size: int):
    """Downscale to a width tier while preserving the complete aspect ratio."""
    thumbnail = image.copy()
    # Passing the source height as the vertical bound makes width the only
    # limiting dimension without upscaling small originals.  The resulting
    # files can therefore be used with standard HTML width descriptors.
    thumbnail.thumbnail((size, thumbnail.height), _PILImage.Resampling.LANCZOS)
    return thumbnail


def _encode_thumbhash(pil) -> str | None:
    try:
        return encode_pil_thumbhash(pil)
    except Exception as exc:
        logger.warning("[thumbnail] thumbhash failed: %s", exc)
        return None


def _phash_parts(phash: str) -> dict[str, int]:
    phash_int_val = int(phash, 16)
    if phash_int_val >= (1 << 63):
        phash_int_val -= 1 << 64

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
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
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
        "ffmpeg",
        "-y",
        "-ss",
        str(seek),
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=True)


def _encode_preview(src: Path, destination: Path, *, concat: bool = False) -> None:
    temporary = destination.with_name(f".{uuid.uuid4().hex}.webm")
    cmd = ["ffmpeg", "-y"]
    if concat:
        cmd.extend(["-f", "concat", "-safe", "0"])
    cmd.extend(
        [
            "-i",
            str(src),
            "-t",
            "3",
            "-vf",
            "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease,fps=12",
            "-an",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "36",
            "-b:v",
            "0",
            str(temporary),
        ]
    )
    try:
        subprocess.run(cmd, capture_output=True, timeout=90, check=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _generate_zip_preview(src: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="jyzrox-ugoira-") as raw_dir:
        directory = Path(raw_dir)
        frames: list[Path] = []
        total_size = 0
        with zipfile.ZipFile(src) as archive:
            for index, info in enumerate(archive.infolist()[:300]):
                suffix = Path(info.filename).suffix.lower()
                if info.is_dir() or suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                    continue
                total_size += info.file_size
                if total_size > 1024 * 1024 * 1024:
                    raise ValueError("Ugoira archive exceeds extraction limit")
                frame = directory / f"{index:06d}{suffix}"
                frame.write_bytes(archive.read(info))
                frames.append(frame)
        if not frames:
            raise ValueError("Ugoira archive contains no supported frames")
        concat = directory / "frames.txt"
        lines: list[str] = []
        for frame in frames:
            escaped = str(frame).replace("'", "'\\''")
            lines.extend([f"file '{escaped}'", "duration 0.083333"])
        last_frame = str(frames[-1]).replace("'", "'\\''")
        lines.append(f"file '{last_frame}'")
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _encode_preview(concat, destination, concat=True)


def _ensure_preview(src: Path, td: Path) -> Path | None:
    destination = td / "preview.webm"
    if destination.exists():
        return destination
    try:
        if zipfile.is_zipfile(src):
            _generate_zip_preview(src, destination)
        else:
            _encode_preview(src, destination)
        return destination
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        logger.warning("[thumbnail] preview %s: %s", src, exc)
        return None


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


def _apply_thumbnail_result(blob, result: _ThumbnailResult) -> None:
    blob.width = result.width
    blob.height = result.height
    blob.duration = result.duration
    if result.phash is not None:
        if blob.phash_int != result.phash_int:
            blob.dedup_scanned_threshold = None
            blob.dedup_scanned_phash_int = None
            blob.dedup_scanned_version = None
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


def _blob_needs_thumbnail(blob) -> bool:
    if blob is None:
        return False
    if not thumbnails_complete_at(thumb_dir(blob.sha256)):
        return True
    if blob.width is None or blob.height is None or blob.thumbhash is None:
        return True
    return blob.media_type != "video" and blob.phash is None


async def _load_gallery_images(session, gallery_id: int) -> tuple[Gallery | None, list[Image]]:
    from sqlalchemy.orm import selectinload

    gallery = await session.get(Gallery, gallery_id)
    if not gallery:
        return None, []

    images = (
        (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .order_by(Image.page_num.asc())
                .options(selectinload(Image.blob))
            )
        )
        .scalars()
        .all()
    )
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
    work = [(img, resolve_blob_path(img.blob, img.external_path)) for img in images if _blob_needs_thumbnail(img.blob)]
    if not work:
        return 0

    results = await asyncio.gather(
        *[_run_thumbnail_in_thread(img.blob.sha256, img.blob.media_type, src) for img, src in work],
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
    logger.info("[thumbnail_cover] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if gallery:
            cover = await select_cover_image(session, gallery_id, gallery.source or "")
            if cover:
                processed = await _process_images(session, [cover], commit_batch=1)

    logger.info("[thumbnail_cover] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}
