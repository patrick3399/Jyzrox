"""Content-Addressable Storage (CAS) service layer."""

import os
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import Blob


def cas_path(sha256: str, ext: str) -> Path:
    """Return the CAS filesystem path for a blob.

    Layout: /data/cas/{sha[:2]}/{sha[2:4]}/{sha}.{ext}
    """
    return Path(settings.data_cas_path) / sha256[:2] / sha256[2:4] / f"{sha256}{ext}"


def cas_url(sha256: str, ext: str) -> str:
    """Return the nginx-served URL for a CAS blob."""
    return f"/media/cas/{sha256[:2]}/{sha256[2:4]}/{sha256}{ext}"


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


def resolve_blob_path(blob: Blob) -> Path:
    """Return the actual filesystem path for a blob (CAS or external)."""
    if blob.storage == "external" and blob.external_path:
        return Path(blob.external_path)
    return cas_path(blob.sha256, blob.extension)


def thumb_dir(sha256: str) -> Path:
    """Return the thumbnail directory for a blob."""
    return Path(settings.data_thumbs_path) / sha256[:2] / sha256[2:4] / sha256


def thumb_url(sha256: str) -> str:
    """Return the 160px thumbnail URL."""
    return f"/media/thumbs/{sha256[:2]}/{sha256[2:4]}/{sha256}/thumb_160.webp"


async def store_blob(
    file_path: Path,
    sha256: str,
    session: AsyncSession,
    *,
    storage: str = "cas",
    external_path: str | None = None,
) -> Blob:
    """Store a file in CAS and upsert the blob record.

    For storage='cas': hardlink the file into the CAS directory.
    For storage='external': only create the DB record (no file copy).

    Returns the Blob record.
    """
    ext = file_path.suffix.lower()  # e.g., '.jpg'
    file_size = file_path.stat().st_size

    # Determine media type from extension
    video_exts = {".mp4", ".webm", ".mkv", ".avi"}
    gif_exts = {".gif"}
    if ext in video_exts:
        media_type = "video"
    elif ext in gif_exts:
        media_type = "gif"
    else:
        media_type = "image"

    # Hardlink into CAS if not external
    if storage == "cas":
        dest = cas_path(sha256, ext)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(str(file_path), str(dest))
            except OSError:
                # Cross-device link: fallback to copy
                file_path.copy(dest)

    # Upsert blob record.
    # ref_count starts at 0 here; callers must increment it only when a new
    # Image row is actually inserted (on_conflict_do_nothing means duplicate
    # re-downloads must NOT inflate ref_count).
    stmt = (
        pg_insert(Blob)
        .values(
            sha256=sha256,
            file_size=file_size,
            media_type=media_type,
            extension=ext,
            storage=storage,
            external_path=external_path,
            ref_count=0,
        )
        .on_conflict_do_update(
            index_elements=["sha256"],
            # No-op update so that RETURNING still returns the existing row
            # without touching ref_count.
            set_={"sha256": pg_insert(Blob).excluded.sha256},
        )
        .returning(Blob)
    )

    result = await session.execute(stmt)
    return result.scalar_one()


async def create_library_symlink(source: str, source_id: str, filename: str, blob: Blob) -> None:
    """Create a symlink in /data/library/{source}/{safe_source_id}/ pointing to the blob's actual file."""
    link_dir = library_dir(source, source_id)
    link_dir.mkdir(parents=True, exist_ok=True)

    target = resolve_blob_path(blob)
    link = link_dir / filename

    # Remove existing symlink if any
    if link.is_symlink() or link.exists():
        link.unlink()

    link.symlink_to(target)


async def decrement_ref_count(sha256: str, session: AsyncSession) -> None:
    """Decrement the ref_count of a blob by 1."""
    stmt = update(Blob).where(Blob.sha256 == sha256).values(ref_count=Blob.ref_count - 1)
    await session.execute(stmt)
