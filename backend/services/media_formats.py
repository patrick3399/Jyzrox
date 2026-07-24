"""Canonical media extension and type definitions.

All ingest, discovery, and CAS paths must use this module so a format cannot be
accepted by one pipeline stage and silently reclassified or dropped by another.
"""

from pathlib import Path

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def normalized_extension(path_or_extension: str | Path) -> str:
    """Return a lower-case extension including the leading dot."""
    if isinstance(path_or_extension, Path):
        return path_or_extension.suffix.lower()
    value = path_or_extension.strip().lower()
    if value.startswith("."):
        return value
    suffix = Path(value).suffix.lower()
    return suffix or (f".{value}" if "/" not in value and "\\" not in value else "")


def media_type_for_extension(path_or_extension: str | Path) -> str | None:
    """Map a supported extension to the Blob ``media_type`` value."""
    extension = normalized_extension(path_or_extension)
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension == ".gif":
        return "gif"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    return None
