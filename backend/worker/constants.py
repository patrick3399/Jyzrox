"""Shared constants for the worker package."""

import logging

logger = logging.getLogger("worker")

DISK_LOW_KEY = "system:disk_low"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}
_VIDEO_EXTS = {".mp4", ".webm"}
_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS

# Magic byte signatures for image file validation
_IMAGE_MAGIC = {
    b"\xff\xd8\xff": {".jpg", ".jpeg"},  # JPEG
    b"\x89PNG\r\n\x1a\n": {".png"},  # PNG
    b"GIF87a": {".gif"},  # GIF87a
    b"GIF89a": {".gif"},  # GIF89a
    # AVIF/HEIC: ftyp box at bytes 4-7, handled by the special-case check below
}
