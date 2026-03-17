"""Thumbnail generation job for the worker package."""

import base64
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Blob, Image
from services.cas import resolve_blob_path, thumb_dir
from worker.constants import _VIDEO_EXTS, logger


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


async def generate_single_thumbnail(blob: Blob, src: Path, session: AsyncSession) -> bool:
    """Generate thumbnails + phash + thumbhash for a single blob. Returns True on success."""
    import imagehash
    from PIL import Image as PILImage

    sizes = [160, 360, 720]

    if not src.exists():
        return False

    # Video files: extract metadata + thumbnail frame via ffmpeg
    if blob.media_type == "video":
        td = thumb_dir(blob.sha256)
        td.mkdir(parents=True, exist_ok=True)
        try:
            meta = _ffprobe_metadata(src)
            blob.width = meta["width"]
            blob.height = meta["height"]
            blob.duration = meta["duration"]

            seek = min((meta["duration"] or 0) * 0.1, 1.0) if meta["duration"] else 0
            tmp_frame = td / "frame_tmp.jpg"
            _extract_video_frame(src, tmp_frame, seek)

            with PILImage.open(tmp_frame) as pil:
                rgb = pil.convert("RGB")
                for size in sizes:
                    dest = td / f"thumb_{size}.webp"
                    if dest.exists():
                        continue
                    thumb = rgb.copy()
                    thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                    tmp = dest.with_suffix(".tmp")
                    thumb.save(str(tmp), "WEBP", quality=85)
                    os.rename(tmp, dest)

                # Generate thumbhash from video frame
                try:
                    import thumbhash as _thumbhash
                    thumb_for_hash = pil.convert("RGBA")
                    thumb_for_hash.thumbnail((100, 100))
                    tw, th = thumb_for_hash.size
                    rgba_data = thumb_for_hash.tobytes()
                    hash_bytes = _thumbhash.rgba_to_thumbhash(tw, th, rgba_data)
                    blob.thumbhash = base64.b64encode(hash_bytes).decode()
                except Exception as exc:
                    logger.warning("[thumbnail] thumbhash video failed %s: %s", src, exc)

            tmp_frame.unlink(missing_ok=True)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError, ValueError) as exc:
            logger.error("[thumbnail] video %s: %s", src, exc)
            return False

        return True

    # Image files
    td = thumb_dir(blob.sha256)
    td.mkdir(parents=True, exist_ok=True)

    try:
        with PILImage.open(src) as pil:
            # Store actual dimensions and phash on the blob
            blob.width, blob.height = pil.size
            blob.phash = str(imagehash.phash(pil))
            phash_int_val = int(blob.phash, 16)
            # Convert unsigned 64-bit to signed 64-bit for PostgreSQL BIGINT
            if phash_int_val >= (1 << 63):
                phash_int_val -= (1 << 64)
            blob.phash_int = phash_int_val
            # Store quarter values as signed 16-bit (PostgreSQL SMALLINT range)
            def _to_signed16(v: int) -> int:
                return v - 0x10000 if v >= 0x8000 else v
            blob.phash_q0 = _to_signed16((phash_int_val >> 48) & 0xFFFF)
            blob.phash_q1 = _to_signed16((phash_int_val >> 32) & 0xFFFF)
            blob.phash_q2 = _to_signed16((phash_int_val >> 16) & 0xFFFF)
            blob.phash_q3 = _to_signed16(phash_int_val & 0xFFFF)

            # Generate thumbhash
            try:
                import thumbhash as _thumbhash
                thumb_for_hash = pil.convert("RGBA")
                thumb_for_hash.thumbnail((100, 100))
                tw, th = thumb_for_hash.size
                rgba_data = thumb_for_hash.tobytes()
                hash_bytes = _thumbhash.rgba_to_thumbhash(tw, th, rgba_data)
                blob.thumbhash = base64.b64encode(hash_bytes).decode()
            except Exception as exc:
                logger.warning("[thumbnail] thumbhash failed %s: %s", src, exc)

            rgb = pil.convert("RGB")
            for size in sizes:
                dest = td / f"thumb_{size}.webp"
                if dest.exists():
                    continue
                thumb = rgb.copy()
                thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                tmp = dest.with_suffix(".tmp")
                thumb.save(str(tmp), "WEBP", quality=85)
                os.rename(tmp, dest)

    except (OSError, ValueError) as exc:
        logger.error("[thumbnail] %s: %s", src, exc)
        return False

    return True


async def thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate 160/360/720px WebP thumbnails for all images in a gallery."""
    from sqlalchemy.orm import selectinload

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    processed = 0

    async with AsyncSessionLocal() as session:
        images = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .options(selectinload(Image.blob))
            )
        ).scalars().all()

        for img in images:
            blob = img.blob
            if not blob:
                continue
            src = resolve_blob_path(blob)

            success = await generate_single_thumbnail(blob, src, session)
            if success:
                processed += 1

        await session.commit()

    logger.info("[thumbnail] gallery_id=%d: %d done", gallery_id, processed)

    try:
        from core.events import EventType, emit
        await emit(EventType.THUMBNAILS_GENERATED, resource_type="gallery", resource_id=gallery_id, count=processed)
    except Exception:
        pass

    return {"status": "done", "processed": processed}
