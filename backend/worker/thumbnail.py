"""Thumbnail generation job for the worker package."""

import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Image
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


async def thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate 160/360/720px WebP thumbnails for all images in a gallery."""
    import imagehash
    from PIL import Image as PILImage
    from sqlalchemy.orm import selectinload

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    sizes = [160, 360, 720]
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
            if not src.exists():
                continue

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

                    tmp_frame.unlink(missing_ok=True)
                except (subprocess.SubprocessError, json.JSONDecodeError, OSError, ValueError) as exc:
                    logger.error("[thumbnail] video %s: %s", src, exc)

                processed += 1
                continue

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

                processed += 1
            except (OSError, ValueError) as exc:
                logger.error("[thumbnail] %s: %s", src, exc)

        await session.commit()

    logger.info("[thumbnail] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}
