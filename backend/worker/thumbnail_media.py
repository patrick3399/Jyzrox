"""Image, video and preview helpers used by thumbnail generation."""

import json
import os
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

from PIL import Image as _PILImage

from services.cas import THUMBNAIL_VERSION, THUMBNAIL_VERSION_FILENAME
from worker.constants import logger
from worker.thumbhash_utils import encode_pil_thumbhash


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
