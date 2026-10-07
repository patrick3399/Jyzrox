"""Incremental filesystem → DB sync for link-mode galleries (ADR 0014).

A link gallery's bytes stay in the user's folder, so the folder decides which
pages exist. Reconciling the two is cheap:

1. one ``stat`` of the source directory — an unchanged mtime means nothing was
   added, removed or renamed, and the gallery opens straight from the DB;
2. otherwise ``scandir`` + per-file ``stat`` against the size/mtime fingerprint
   stored on each Image row, hashing only files that are new or changed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import stat as stat_module
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, insert, select, update

import core.queue
from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import ExcludedBlob, Gallery, Image
from services.cas import (
    create_library_symlink,
    decrement_ref_count,
    increment_ref_count,
    library_dir,
    store_blob,
)
from services.image_magic import validate_image_magic
from services.library_sidecar import sidecar_payload_from_gallery, write_gallery_sidecar
from services.media_formats import MEDIA_EXTENSIONS, VIDEO_EXTENSIONS
from services.source_identity import SourceFileChangedError, SourceFileIdentity, hash_file_with_identity
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails

logger = logging.getLogger(__name__)

# A file modified this recently may still be mid-copy; leave it for the next sync.
SETTLE_NS = 2_000_000_000

_NATURAL_SORT_RE = re.compile(r"(\d+)")


@dataclass(frozen=True, slots=True)
class FileStat:
    """One media file found in a source directory."""

    path: str
    name: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class KnownImage:
    """The DB's view of one link-mode page."""

    image_id: int
    external_path: str
    sha256: str
    size: int | None
    mtime_ns: int | None


@dataclass(slots=True)
class LinkSyncPlan:
    """What a sync has to do, decided from stat data alone."""

    unchanged: list[KnownImage] = field(default_factory=list)
    adopt: list[tuple[KnownImage, FileStat]] = field(default_factory=list)
    changed: list[tuple[KnownImage, FileStat]] = field(default_factory=list)
    new: list[FileStat] = field(default_factory=list)
    missing: list[KnownImage] = field(default_factory=list)
    unsettled: list[FileStat] = field(default_factory=list)

    @property
    def needs_hash(self) -> list[FileStat]:
        return [*self.new, *(file for _, file in self.changed)]


def _natural_sort_key(name: str) -> tuple[tuple[int, str | int], ...]:
    """Human page order: 1, 2, 10 instead of 1, 10, 2."""
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold()) for part in _NATURAL_SORT_RE.split(name))


def plan_link_sync(known: Iterable[KnownImage], files: Iterable[FileStat], *, now_ns: int) -> LinkSyncPlan:
    """Classify every file and every known page without reading file contents."""
    known = list(known)
    by_path = {image.external_path: image for image in known}
    plan = LinkSyncPlan()
    seen: set[str] = set()

    for file in sorted(files, key=lambda item: _natural_sort_key(item.name)):
        seen.add(file.path)
        image = by_path.get(file.path)
        settled = now_ns - file.mtime_ns >= SETTLE_NS
        if image is None:
            (plan.new if settled else plan.unsettled).append(file)
        elif image.size is None or image.mtime_ns is None:
            # Row predates fingerprints: trust the bytes, record the stat.
            plan.adopt.append((image, file))
        elif (image.size, image.mtime_ns) == (file.size, file.mtime_ns):
            plan.unchanged.append(image)
        elif settled:
            plan.changed.append((image, file))
        else:
            plan.unsettled.append(file)

    plan.missing = [image for image in known if image.external_path not in seen]
    return plan


def scan_media_files(directory: Path) -> list[FileStat]:
    """List the media files directly inside ``directory`` with their stat."""
    files: list[FileStat] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if Path(entry.name).suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            try:
                if not entry.is_file():
                    continue
                stat = entry.stat()
            except OSError:
                continue
            files.append(FileStat(path=entry.path, name=entry.name, size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return files


def library_root_available(root: str | None) -> bool:
    """Return False when a library root is missing or empty.

    An unmounted volume shows up as an absent path or an empty mount point. In
    that state every link file looks deleted, so callers must not remove rows.
    """
    if not root:
        return True
    try:
        with os.scandir(root) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


# New pages are committed in chunks so they are readable while the rest is hashed.
LINK_SYNC_CHUNK = 20

_LOCK_TTL_SECONDS = 900
_LOCK_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"

LinkStates = list[tuple[Path, str | None]]


@dataclass(slots=True)
class LinkSyncResult:
    status: str
    added: int = 0
    removed: int = 0
    renamed: int = 0
    replaced: int = 0
    pending: int = 0
    pages: int | None = None

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.renamed or self.replaced)

    def as_dict(self) -> dict:
        return {**asdict(self), "changed": self.changed}


def _lock_key(gallery_id: int) -> str:
    return f"link-sync:lock:{gallery_id}"


async def sync_link_gallery(
    gallery_id: int,
    *,
    redis,
    force: bool = False,
    max_hash_files: int | None = None,
    max_hash_bytes: int | None = None,
) -> LinkSyncResult:
    """Reconcile one link gallery with its source directory.

    ``force`` skips the directory-mtime shortcut (needed to notice a file
    rewritten in place). ``max_hash_*`` bound the work a caller will do inline;
    over the limit nothing is changed and the status is ``deferred``.
    """
    token = uuid.uuid4().hex
    # One sync per gallery: two concurrent runs would both insert the same new
    # file under different page numbers (HR-006).
    if not await redis.set(_lock_key(gallery_id), token, nx=True, ex=_LOCK_TTL_SECONDS):
        return LinkSyncResult(status="busy")
    try:
        return await _sync_locked(gallery_id, force=force, max_hash_files=max_hash_files, max_hash_bytes=max_hash_bytes)
    finally:
        await redis.eval(_LOCK_RELEASE_LUA, 1, _lock_key(gallery_id), token)


async def _hash(file: FileStat) -> tuple[str, SourceFileIdentity] | None:
    try:
        return await asyncio.to_thread(hash_file_with_identity, Path(file.path))
    except (OSError, SourceFileChangedError) as exc:
        logger.warning("[link_sync] skipping %s: %s", file.path, exc)
        return None


def _restore_links(states: LinkStates) -> None:
    """Undo symlinks created for rows that did not commit."""
    for link, previous_target in reversed(states):
        try:
            if link.is_symlink():
                link.unlink()
            if previous_target is not None:
                link.symlink_to(previous_target)
        except OSError as exc:
            logger.error("[link_sync] failed to restore library link %s: %s", link, exc)


async def _expose(source: str, source_id: str, filename: str, blob, external_path: str, states: LinkStates) -> None:
    link = library_dir(source, source_id) / filename
    if link.exists() and not link.is_symlink():
        raise FileExistsError(f"refusing to replace non-symlink library file: {link}")
    states.append((link, os.readlink(link) if link.is_symlink() else None))
    await create_library_symlink(source, source_id, filename, blob, external_path=external_path)


async def _commit(session, states: LinkStates) -> None:
    try:
        await session.commit()
    except Exception:
        _restore_links(states)
        raise
    states.clear()


async def _page_count(session, gallery_id: int) -> int:
    return (await session.execute(select(func.count(Image.id)).where(Image.gallery_id == gallery_id))).scalar_one()


async def _sync_locked(
    gallery_id: int,
    *,
    force: bool,
    max_hash_files: int | None,
    max_hash_bytes: int | None,
) -> LinkSyncResult:
    result = LinkSyncResult(status="synced")
    removed_shas: list[str] = []
    stale_link_names: list[str] = []
    link_states: LinkStates = []
    needs_thumbnails = False
    sidecar_payload = None

    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if gallery is None:
            return LinkSyncResult(status="not_found")
        if gallery.deleted_at is not None:
            # HR-014: only trash GC may touch a trashed gallery.
            return LinkSyncResult(status="skipped_trashed")
        if gallery.import_mode != "link" or not gallery.source_path:
            return LinkSyncResult(status="not_link", pages=gallery.pages)
        if gallery.download_status == "importing":
            # The first import owns the gallery until it reaches a terminal status.
            return LinkSyncResult(status="importing", pages=gallery.pages)

        source, source_id = gallery.source, gallery.source_id
        source_dir = Path(gallery.source_path)

        if not await asyncio.to_thread(library_root_available, gallery.library_path):
            logger.error(
                "[link_sync] gallery_id=%d: library root %s is missing or empty; nothing removed",
                gallery_id,
                gallery.library_path,
            )
            return LinkSyncResult(status="root_unavailable", pages=gallery.pages)
        try:
            dir_stat = await asyncio.to_thread(source_dir.stat)
        except OSError:
            return LinkSyncResult(status="source_missing", pages=gallery.pages)
        if not stat_module.S_ISDIR(dir_stat.st_mode):
            return LinkSyncResult(status="source_missing", pages=gallery.pages)

        # Read before listing: an entry added during the scan moves the mtime
        # past this value, so the next sync still sees a change.
        dir_mtime_ns = dir_stat.st_mtime_ns
        if not force and gallery.source_dir_mtime_ns == dir_mtime_ns:
            return LinkSyncResult(status="unchanged", pages=gallery.pages)

        files = await asyncio.to_thread(scan_media_files, source_dir)
        rows = (
            await session.execute(
                select(
                    Image.id,
                    Image.page_num,
                    Image.external_path,
                    Image.blob_sha256,
                    Image.source_size,
                    Image.source_mtime_ns,
                ).where(Image.gallery_id == gallery_id)
            )
        ).all()
        known = [
            KnownImage(
                image_id=row.id,
                external_path=row.external_path,
                sha256=row.blob_sha256,
                size=row.source_size,
                mtime_ns=row.source_mtime_ns,
            )
            for row in rows
            # Merged galleries keep pages whose files live in another folder;
            # this sync only owns files directly inside source_dir.
            if row.external_path and os.path.dirname(row.external_path) == str(source_dir)
        ]
        plan = plan_link_sync(known, files, now_ns=time.time_ns())

        to_hash = plan.needs_hash
        over_files = max_hash_files is not None and len(to_hash) > max_hash_files
        over_bytes = max_hash_bytes is not None and sum(file.size for file in to_hash) > max_hash_bytes
        if over_files or over_bytes:
            return LinkSyncResult(status="deferred", pending=len(to_hash), pages=gallery.pages)

        excluded = set(
            (await session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
            .scalars()
            .all()
        )
        missing_ids = {image.image_id for image in plan.missing}
        present_shas = {row.blob_sha256 for row in rows if row.id not in missing_ids}
        missing_by_sha: dict[str, list[KnownImage]] = defaultdict(list)
        for image in plan.missing:
            missing_by_sha[image.sha256].append(image)
        max_page = max((row.page_num for row in rows), default=0)
        clean = not plan.unsettled
        last_event = 0.0

        try:
            # 1. Rows that predate fingerprints: record the stat, do not re-read.
            if plan.adopt:
                await session.execute(
                    update(Image),
                    [
                        {"id": image.image_id, "source_size": file.size, "source_mtime_ns": file.mtime_ns}
                        for image, file in plan.adopt
                    ],
                )

            # 2. New files: a rename, a duplicate, or a new page.
            in_chunk = 0
            for file in plan.new:
                is_video = Path(file.name).suffix.lower() in VIDEO_EXTENSIONS
                if not is_video and not validate_image_magic(Path(file.path)):
                    logger.warning("[link_sync] gallery_id=%d: %s is not a valid image", gallery_id, file.name)
                    continue
                hashed = await _hash(file)
                if hashed is None:
                    clean = False
                    continue
                sha256, identity = hashed
                if sha256 in excluded:
                    continue

                renamed_from = missing_by_sha.get(sha256)
                if renamed_from:
                    image = renamed_from.pop()
                    blob = await store_blob(
                        Path(file.path), sha256, session, storage="external", external_path=file.path
                    )
                    await session.flush()
                    await session.execute(
                        update(Image)
                        .where(Image.id == image.image_id)
                        .values(
                            external_path=file.path,
                            filename=file.name,
                            source_size=identity.size,
                            source_mtime_ns=identity.mtime_ns,
                        )
                    )
                    await _expose(source, source_id, file.name, blob, file.path, link_states)
                    stale_link_names.append(Path(image.external_path).name)
                    present_shas.add(sha256)
                    result.renamed += 1
                elif sha256 in present_shas:
                    # Same bytes as an existing page of this gallery (HR-006).
                    continue
                else:
                    blob = await store_blob(
                        Path(file.path), sha256, session, storage="external", external_path=file.path
                    )
                    await session.flush()
                    max_page += 1
                    await session.execute(
                        insert(Image).values(
                            gallery_id=gallery_id,
                            page_num=max_page,
                            filename=file.name,
                            blob_sha256=sha256,
                            external_path=file.path,
                            source_size=identity.size,
                            source_mtime_ns=identity.mtime_ns,
                            added_at=datetime.now(UTC),
                        )
                    )
                    await increment_ref_count(sha256, session)
                    await _expose(source, source_id, file.name, blob, file.path, link_states)
                    present_shas.add(sha256)
                    result.added += 1
                    needs_thumbnails = True

                in_chunk += 1
                if in_chunk >= LINK_SYNC_CHUNK:
                    in_chunk = 0
                    gallery.pages = await _page_count(session, gallery_id)
                    await _commit(session, link_states)
                    if time.monotonic() - last_event >= 1.0:
                        last_event = time.monotonic()
                        await emit_safe(
                            EventType.GALLERY_UPDATED,
                            resource_type="gallery",
                            resource_id=gallery_id,
                            reason="link_sync_progress",
                        )

            # 3. Same name, different fingerprint.
            for image, file in plan.changed:
                hashed = await _hash(file)
                if hashed is None:
                    clean = False
                    continue
                sha256, identity = hashed
                fingerprint = {"source_size": identity.size, "source_mtime_ns": identity.mtime_ns}
                if sha256 == image.sha256:
                    # Touched, not edited.
                    await session.execute(update(Image).where(Image.id == image.image_id).values(**fingerprint))
                    continue
                if sha256 in excluded or sha256 in present_shas:
                    # The new bytes are hidden here or duplicate another page.
                    await session.execute(delete(Image).where(Image.id == image.image_id))
                    await decrement_ref_count(image.sha256, session)
                    removed_shas.append(image.sha256)
                    stale_link_names.append(file.name)
                    result.removed += 1
                    continue
                await store_blob(Path(file.path), sha256, session, storage="external", external_path=file.path)
                await session.flush()
                await session.execute(
                    update(Image).where(Image.id == image.image_id).values(blob_sha256=sha256, **fingerprint)
                )
                await increment_ref_count(sha256, session)
                await decrement_ref_count(image.sha256, session)
                removed_shas.append(image.sha256)
                present_shas.add(sha256)
                result.replaced += 1
                needs_thumbnails = True

            # 4. Files that are gone and were not matched as a rename.
            for images in missing_by_sha.values():
                for image in images:
                    await session.execute(delete(Image).where(Image.id == image.image_id))
                    await decrement_ref_count(image.sha256, session)
                    removed_shas.append(image.sha256)
                    stale_link_names.append(Path(image.external_path).name)
                    result.removed += 1

            # 5. Gallery bookkeeping.
            pages = await _page_count(session, gallery_id)
            gallery.pages = pages
            if pages == 0:
                gallery.download_status = "missing"
            elif clean and gallery.download_status in ("missing", "partial", "failed"):
                gallery.download_status = "complete"
            # Only a clean pass may arm the directory-mtime shortcut.
            gallery.source_dir_mtime_ns = dir_mtime_ns if clean else None
            gallery.last_scanned_at = datetime.now(UTC)
            if result.changed:
                gallery.metadata_updated_at = func.now()
                sidecar_payload = sidecar_payload_from_gallery(gallery)
            await _commit(session, link_states)
        except Exception:
            _restore_links(link_states)
            raise

        result.pages = pages
        if removed_shas:
            await cleanup_unreferenced_thumbnails(session, removed_shas)

    # Rows are committed; the remaining work is best-effort.
    link_dir = library_dir(source, source_id)
    for name in stale_link_names:
        link = link_dir / name
        try:
            if link.is_symlink() and not link.exists():
                link.unlink()
        except OSError as exc:
            logger.warning("[link_sync] could not remove stale link %s: %s", link, exc)

    if sidecar_payload is not None:
        await write_gallery_sidecar(source, source_id, sidecar_payload)
    if needs_thumbnails:
        await core.queue.enqueue(
            "cover_thumbnail_job", gallery_id=gallery_id, _timeout=300, _job_id=f"cover-thumbnail:{gallery_id}"
        )
        await core.queue.enqueue(
            "thumbnail_job", gallery_id=gallery_id, _timeout=3600, _job_id=f"thumbnail:{gallery_id}"
        )
    if result.changed:
        await emit_safe(
            EventType.GALLERY_UPDATED,
            resource_type="gallery",
            resource_id=gallery_id,
            reason="link_sync",
            pages=result.pages,
            added=result.added,
            removed=result.removed,
        )
    return result
