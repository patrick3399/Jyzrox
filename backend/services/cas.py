"""Content-Addressable Storage (CAS) service layer."""

import asyncio
import os
import shutil
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import Blob, BlobLocation, Image
from services.media_formats import media_type_for_extension

THUMBNAIL_SIZES = (160, 360, 720)
THUMBNAIL_VERSION = 2
THUMBNAIL_VERSION_FILENAME = ".thumbnail-version"


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


def resolve_blob_path(blob: Blob, external_path: str | None = None) -> Path:
    """Return the filesystem path for a blob or a specific image binding."""
    if external_path:
        return Path(external_path)
    if blob.storage == "external" and blob.external_path:
        # Compatibility fallback for callers that do not represent one Image.
        # New image-bound reads pass ``external_path`` explicitly.
        return Path(blob.external_path)
    return cas_path(blob.sha256, blob.extension)


async def resolve_readable_blob_path(session: AsyncSession, blob: Blob) -> Path | None:
    """Return a path whose bytes are actually present, or None if none are.

    For callers that hold a Blob but no particular Image — tier-3 dedup compares
    blob *pairs* — the scalar ``Blob.external_path`` is not enough: it records
    only one of possibly several locations and ``store_blob`` deliberately no
    longer refreshes it, so it can point at a file that has since moved while
    another Image's binding for the same bytes is still valid. Reading the
    scalar alone made such pairs fail the pixel diff and degrade to
    ``quality_conflict`` even though the content was right there.

    CAS wins when present because it is the durable copy; otherwise prefer an
    Image-bound location, then any registered BlobLocation, then the legacy
    scalar.
    """
    candidates: list[Path] = []
    if blob.storage != "external":
        candidates.append(cas_path(blob.sha256, blob.extension))

    bound = (
        (
            await session.execute(
                select(Image.external_path)
                .where(Image.blob_sha256 == blob.sha256, Image.external_path.is_not(None))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    registered = (
        (await session.execute(select(BlobLocation.external_path).where(BlobLocation.blob_sha256 == blob.sha256)))
        .scalars()
        .all()
    )

    seen: set[str] = set()
    for raw in [*bound, *registered, blob.external_path]:
        if raw and raw not in seen:
            seen.add(raw)
            candidates.append(Path(raw))
    # CAS is also worth a look for an 'external' blob that was later ingested.
    if blob.storage == "external":
        candidates.append(cas_path(blob.sha256, blob.extension))

    def _first_existing() -> Path | None:
        return next((p for p in candidates if p.is_file()), None)

    return await asyncio.to_thread(_first_existing)


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


def thumb_variants(sha256: str) -> dict[str, str]:
    """Return every responsive thumbnail candidate for a blob."""
    return {str(size): thumb_url(sha256, size) for size in THUMBNAIL_SIZES}


def thumb_srcset(sha256: str) -> str:
    """Return a width-descriptor srcset for local thumbnail candidates."""
    return ", ".join(f"{thumb_url(sha256, size)} {size}w" for size in THUMBNAIL_SIZES)


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
    if storage == "external" and not external_path:
        raise ValueError("external_path is required for external blob storage")

    ext = file_path.suffix.lower()  # e.g., '.jpg'
    file_size = file_path.stat().st_size

    media_type = media_type_for_extension(ext)
    if media_type is None:
        raise ValueError(f"Unsupported media extension: {ext}")

    # Upsert blob record FIRST so the filesystem write below can use the
    # canonical extension: identical bytes arriving under a different filename
    # extension must not create a second CAS file (edge case #44) — the
    # conflict path keeps the first-stored extension.
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
            # CAS is the durable representation when it exists. External paths
            # are recorded independently below and bound to Image rows; the
            # legacy scalar path must never be overwritten last-writer-wins.
            set_={
                "storage": case(
                    (pg_insert(Blob).excluded.storage == "cas", "cas"),
                    else_=Blob.storage,
                ),
            },
        )
        .returning(Blob)
    )

    result = await session.execute(stmt)
    blob = result.scalar_one()

    if storage == "external" and external_path is not None:
        location_stmt = (
            pg_insert(BlobLocation)
            .values(blob_sha256=sha256, external_path=external_path)
            .on_conflict_do_nothing(index_elements=["blob_sha256", "external_path"])
        )
        await session.execute(location_stmt)

    # Hardlink into CAS if not external, at the canonical-extension path
    if storage == "cas":
        dest = cas_path(sha256, blob.extension)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(str(file_path), str(dest))
            except FileExistsError:
                # Lost a race with a concurrent worker importing the same blob:
                # the content-addressed file is already in place (same bytes by
                # construction), so this is success. Falling through to the copy
                # fallback would overwrite a file readers may already be serving.
                pass
            except OSError:
                # Cross-device link: copy to a temp file and atomically promote
                # so concurrent readers never observe a partially written blob.
                tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
                try:
                    shutil.copy2(str(file_path), str(tmp))
                    os.replace(str(tmp), str(dest))
                finally:
                    tmp.unlink(missing_ok=True)

    return blob


async def create_library_symlink(
    source: str,
    source_id: str,
    filename: str,
    blob: Blob,
    *,
    external_path: str | None = None,
) -> None:
    """Create a symlink in /data/library/{source}/{safe_source_id}/ pointing to the blob's actual file."""
    try:
        link_dir = ensure_library_dir(source, source_id)
    except LibraryDirCollisionError as exc:
        from services.cache import push_system_alert

        await push_system_alert(str(exc))
        raise

    target = resolve_blob_path(blob, external_path)
    link = link_dir / filename

    # Remove existing symlink if any
    if link.is_symlink() or link.exists():
        link.unlink()

    # CAS blobs live under the same data volume as the library tree, so use a
    # RELATIVE target. The /data volume is mounted at a different absolute path
    # inside the container (/data) than on the host (${JYZROX_DATA_ROOT}/data);
    # a relative link (library/ and cas/ are siblings) resolves correctly in
    # both, while an absolute /data/cas/... target dangles when the tree is
    # browsed from the host (file browser / Samba). External blobs live outside
    # the data volume and rely on an identical bind-mount path, so they keep an
    # absolute target.
    if external_path or (blob.storage == "external" and blob.external_path):
        link.symlink_to(target)
    else:
        link.symlink_to(os.path.relpath(target, link_dir))


async def adjust_ref_count(sha256: str, delta: int, session: AsyncSession) -> None:
    """Adjust a Blob reference count when Image rows are attached or detached."""
    if delta == 0:
        return
    stmt = update(Blob).where(Blob.sha256 == sha256).values(ref_count=Blob.ref_count + delta)
    await session.execute(stmt)


async def increment_ref_count(sha256: str, session: AsyncSession, amount: int = 1) -> None:
    """Increment a Blob reference count for newly attached Image rows."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    await adjust_ref_count(sha256, amount, session)


async def decrement_ref_count(sha256: str, session: AsyncSession, amount: int = 1) -> None:
    """Decrement a Blob reference count for detached Image rows."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    await adjust_ref_count(sha256, -amount, session)
