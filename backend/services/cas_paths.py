"""CAS path, URL, library-directory and thumbnail-location helpers."""

import asyncio
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from core.config import settings
from db.models import Blob

THUMBNAIL_SIZES = (160, 360, 720)
THUMBNAIL_VERSION = 2
THUMBNAIL_VERSION_FILENAME = ".thumbnail-version"

# Thumbnail stats on the NFS data root are latency-bound (~0.5 ms each when
# cold), so a bounded pool overlaps them: 3000 cold checks took 1.46 s one by
# one and 0.18 s across 16 threads.
_THUMB_CHECK_WORKERS = 16
_thumb_check_pool = ThreadPoolExecutor(max_workers=_THUMB_CHECK_WORKERS, thread_name_prefix="thumb-check")


def cas_path(sha256: str, ext: str) -> Path:
    """Return the CAS filesystem path for a blob.

    Layout: /data/cas/{sha[:2]}/{sha[2:4]}/{sha}.{ext}
    """
    return Path(settings.data_cas_path) / sha256[:2] / sha256[2:4] / f"{sha256}{ext}"


def cas_url(sha256: str, ext: str) -> str:
    """Return the nginx-served URL for a CAS blob."""
    return f"/media/cas/{sha256[:2]}/{sha256[2:4]}/{sha256}{ext}"


def library_url(external_path: str) -> str:
    """Return the nginx-served ``/media/libraries/`` URL for an external blob.

    ``external_path`` is a raw filesystem path under ``/mnt`` whose final
    segment is an arbitrary source filename. Such names routinely contain
    characters that are reserved in a URL — most damagingly ``#`` and ``?``,
    which a browser interprets as the fragment/query delimiter and *truncates*
    the ``<img src>`` request at, so the image never loads (roughly half of the
    shamakho library filenames carry a ``#``). Percent-encode every segment so
    the URL the browser receives is well-formed; ``media_authz`` unquotes it
    back to match the Image-bound external path and nginx's ``alias`` decodes it for
    the filesystem lookup, so the round-trip is preserved.
    """
    return quote(external_path.replace("/mnt/", "/media/libraries/", 1), safe="/")


def image_file_url(blob: Blob | None, external_path: str | None = None) -> str | None:
    """Return the nginx-served URL for one image's original file.

    Link-mode pages keep their bytes in the user's folder and have no CAS file,
    so an Image-bound ``external_path`` is honoured before the blob check. That
    also covers a pending link page, which has no blob yet.
    """
    if external_path:
        return library_url(external_path)
    if blob is None:
        return None
    if blob.storage == "external" and blob.external_path:
        # Compatibility for callers/tests without an Image binding. Migrated
        # production Image rows carry their own external_path.
        return library_url(blob.external_path)
    return cas_url(blob.sha256, blob.extension)


def safe_source_id(source_id: str) -> str:
    """Sanitize a source_id for use as a filesystem path component.

    Replaces '/' with '__', strips '..' to prevent path traversal,
    and strips leading/trailing whitespace.
    """
    return source_id.strip().replace("/", "__").replace("..", "_")


def library_dir(source: str, source_id: str) -> Path:
    """Return the library symlink directory for a gallery.

    Layout: /data/library/{source}/{safe_source_id}/
    """
    return Path(settings.data_library_path) / source / safe_source_id(source_id)


OWNER_MARKER_FILENAME = ".gallery-owner"


class LibraryDirCollisionError(RuntimeError):
    """Two distinct (source, source_id) pairs sanitize to the same library dir (audit #45)."""


def ensure_library_dir(source: str, source_id: str) -> Path:
    """Create or validate the library symlink dir for a gallery.

    safe_source_id() is not injective ('a/b' sanitizes to 'a__b', colliding
    with a literal 'a__b'), so the dir carries an ownership marker recording
    the raw (source, source_id). Reuse by a different identity raises instead
    of silently mixing two galleries' symlinks (audit #45). Dirs created
    before the marker existed are adopted on first touch.
    """
    d = library_dir(source, source_id)
    owner = f"{source}:{source_id}"
    marker = d / OWNER_MARKER_FILENAME
    if d.exists():
        try:
            existing = marker.read_text(encoding="utf-8").strip()
        except OSError:
            existing = None
        if existing is not None and existing != owner:
            raise LibraryDirCollisionError(
                f"library dir {d} is owned by {existing!r}; refusing to reuse it for {owner!r} "
                f"(safe_source_id collision, audit #45)"
            )
        if existing is None:
            marker.write_text(owner, encoding="utf-8")
        return d
    d.mkdir(parents=True, exist_ok=True)
    marker.write_text(owner, encoding="utf-8")
    return d


def thumb_dir(sha256: str) -> Path:
    """Return the thumbnail directory for a blob."""
    return Path(settings.data_thumbs_path) / sha256[:2] / sha256[2:4] / sha256


def thumbnails_complete(sha256: str) -> bool:
    """Return whether every current-version thumbnail tier exists."""
    return thumbnails_complete_at(thumb_dir(sha256))


def thumbnails_complete_at(directory: Path) -> bool:
    """Return whether a thumbnail directory contains a complete current set."""
    try:
        version = int((directory / THUMBNAIL_VERSION_FILENAME).read_text(encoding="ascii").strip())
    except OSError, ValueError:
        return False
    return version == THUMBNAIL_VERSION and all(
        (directory / f"thumb_{size}.webp").is_file() for size in THUMBNAIL_SIZES
    )


def thumb_url(sha256: str, size: int = 160) -> str:
    """Return a URL for one of the pre-generated thumbnail width tiers."""
    if size not in THUMBNAIL_SIZES:
        raise ValueError(f"Unsupported thumbnail size: {size}")
    return f"/media/thumbs/{sha256[:2]}/{sha256[2:4]}/{sha256}/thumb_{size}.webp"


def _has_base_thumb(sha256: str) -> bool:
    return (thumb_dir(sha256) / "thumb_160.webp").exists()


async def existing_base_thumbs(sha256s: Iterable[str | None]) -> set[str]:
    """Return the blobs among ``sha256s`` whose 160px thumbnail exists.

    Each distinct blob is checked once, off the event loop: a Reader request
    lists every page of a gallery, and stat-ing them inline blocked the whole
    API worker for seconds on large galleries.
    """
    unique = list(dict.fromkeys(sha for sha in sha256s if sha))
    if not unique:
        return set()
    present = await asyncio.to_thread(lambda: list(_thumb_check_pool.map(_has_base_thumb, unique)))
    return {sha for sha, ok in zip(unique, present, strict=True) if ok}


def thumb_variants(sha256: str) -> dict[str, str]:
    """Return every responsive thumbnail candidate for a blob."""
    return {str(size): thumb_url(sha256, size) for size in THUMBNAIL_SIZES}


def thumb_srcset(sha256: str) -> str:
    """Return a width-descriptor srcset for local thumbnail candidates."""
    return ", ".join(f"{thumb_url(sha256, size)} {size}w" for size in THUMBNAIL_SIZES)
