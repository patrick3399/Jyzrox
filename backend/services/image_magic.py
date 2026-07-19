"""Image magic-byte validation, shared by routers and worker jobs."""

from pathlib import Path

# Magic byte signatures for image file validation
IMAGE_MAGIC = {
    b"\xff\xd8\xff": {".jpg", ".jpeg"},  # JPEG
    b"\x89PNG\r\n\x1a\n": {".png"},  # PNG
    b"GIF87a": {".gif"},  # GIF87a
    b"GIF89a": {".gif"},  # GIF89a
    # AVIF/HEIC: ftyp box at bytes 4-7, handled by the special-case check below
}


def validate_image_magic(file_path: Path) -> bool:
    """Validate that a file's content matches expected image magic bytes.

    Returns True if the file appears to be a valid image based on its
    magic bytes matching its file extension. Returns False for mismatches.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
    except OSError:
        return False

    if len(header) < 3:
        return False

    ext = file_path.suffix.lower()

    for magic, valid_exts in IMAGE_MAGIC.items():
        if header.startswith(magic):
            return ext in valid_exts

    # Special case: WebP needs RIFF + WEBP check
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ext == ".webp"

    # Special case: AVIF/HEIC ftyp box (offset 4 = 'ftyp')
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return ext in {".avif", ".heic"}

    # Unknown magic — reject
    return False
