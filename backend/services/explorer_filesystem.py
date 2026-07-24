"""Safe physical-library traversal shared by Explorer API and worker jobs."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LibraryPath
from services.media_formats import MEDIA_EXTENSIONS


async def get_enabled_library_root(db: AsyncSession, library_id: int) -> tuple[LibraryPath, Path]:
    library = await db.get(LibraryPath, library_id)
    if library is None or not library.enabled:
        raise HTTPException(status_code=404, detail="Library path not found")
    root = Path(library.path).resolve(strict=False)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Library path is unavailable")
    return library, root


def resolve_library_relative(root: Path, relative_path: str, *, require_directory: bool | None = None) -> Path:
    """Resolve a POSIX relative path and reject traversal and symlink escapes."""
    raw = PurePosixPath(relative_path or ".")
    if raw.is_absolute() or ".." in raw.parts:
        raise HTTPException(status_code=400, detail="Invalid library-relative path")
    try:
        candidate = (root / Path(*raw.parts)).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="Library entry not found")
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Library path escapes the configured root")
    if require_directory is True and not candidate.is_dir():
        raise HTTPException(status_code=400, detail="Expected a directory")
    if require_directory is False and not candidate.is_file():
        raise HTTPException(status_code=400, detail="Expected a file")
    return candidate


def relative_posix(root: Path, path: Path) -> str:
    value = path.relative_to(root).as_posix()
    return "" if value == "." else value


def folder_stats_key(library_id: int, relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return f"explorer:folder-stats:{library_id}:{digest}"


def folder_stats_job_id(library_id: int, relative_path: str) -> str:
    return folder_stats_key(library_id, relative_path).replace(":", "-")


async def read_folder_stats(redis: Any, library_id: int, relative_path: str) -> dict[str, Any] | None:
    raw = await redis.get(folder_stats_key(library_id, relative_path))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def scan_folder_stats(root: Path, directory: Path) -> dict[str, Any]:
    """Recursively count physical bytes without following external symlinks."""
    total_bytes = 0
    file_count = 0
    media_count = 0
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        current_path = Path(current)
        safe_dirs: list[str] = []
        for dirname in dirnames:
            child = current_path / dirname
            try:
                resolved = child.resolve(strict=True)
            except OSError:
                continue
            if resolved.is_relative_to(root) and not child.is_symlink():
                safe_dirs.append(dirname)
        dirnames[:] = safe_dirs
        for filename in filenames:
            path = current_path / filename
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                total_bytes += resolved.stat().st_size
            except OSError:
                continue
            file_count += 1
            if resolved.suffix.lower() in MEDIA_EXTENSIONS:
                media_count += 1
    return {
        "physical_bytes": total_bytes,
        "file_count": file_count,
        "media_count": media_count,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def detect_media_type(path: Path) -> str | None:
    """Validate common media signatures before serving a raw library file."""
    try:
        with path.open("rb") as stream:
            head = stream.read(32)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in {b"avif", b"avis", b"heic", b"heix", b"mif1"}:
            return "image/avif" if brand in {b"avif", b"avis"} else "image/heic"
        return "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    return None
