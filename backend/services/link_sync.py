"""Stat-only filesystem → DB sync for link-mode galleries (ADR 0015).

A link gallery's bytes stay in the user's folder, so the folder decides which
pages exist. Reconciling the two never reads file contents:

1. one ``stat`` of the source directory — an unchanged mtime means nothing was
   added, removed or renamed, and the gallery opens straight from the DB;
2. otherwise ``scandir`` + per-file ``stat`` against the size/mtime fingerprint
   stored on each Image row. New files become *pending* pages (no blob yet,
   served through ``external_path``), vanished files are removed, a vanished
   page and a new file with an identical fingerprint are a rename, and a page
   whose fingerprint changed goes back to pending.

Hashing and Blob creation happen afterwards in a background job.
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat as stat_module
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import BlobLocation, Gallery, Image
from services.cas import decrement_ref_count, library_dir
from services.library_sidecar import sidecar_payload_from_gallery, write_gallery_sidecar
from services.link_sync_hash import (
    LinkHashResult,
    enqueue_link_hash,
    hash_pending_images,
)
from services.link_sync_links import LinkStates, LinkSyncResult, _commit, _expose, _restore_links, _valid_media
from services.link_sync_plan import (
    SETTLE_NS,
    FileStat,
    KnownImage,
    _active_page_count,
    _pending_count,
    library_root_available,
    pair_renames,
    plan_link_sync,
    scan_media_files,
)
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails

__all__ = [
    "SETTLE_NS",
    "FileStat",
    "KnownImage",
    "LinkHashResult",
    "LinkSyncResult",
    "enqueue_link_hash",
    "hash_pending_images",
    "library_root_available",
    "pair_renames",
    "plan_link_sync",
    "scan_media_files",
    "sync_link_gallery",
]

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 900
_LOCK_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


def _lock_key(gallery_id: int) -> str:
    return f"link-sync:lock:{gallery_id}"


async def sync_link_gallery(gallery_id: int, *, redis, force: bool = False) -> LinkSyncResult:
    """Reconcile one link gallery with its source directory.

    ``force`` skips the directory-mtime shortcut (needed to notice a file
    rewritten in place). Never hashes: when pending pages remain the hash job
    is queued before returning.
    """
    token = uuid.uuid4().hex
    # One sync per gallery: two concurrent runs would both insert the same new
    # file under different page numbers (HR-006).
    if not await redis.set(_lock_key(gallery_id), token, nx=True, ex=_LOCK_TTL_SECONDS):
        return LinkSyncResult(status="busy")
    try:
        return await _sync_locked(gallery_id, force=force)
    finally:
        await redis.eval(_LOCK_RELEASE_LUA, 1, _lock_key(gallery_id), token)


async def _sync_locked(gallery_id: int, *, force: bool) -> LinkSyncResult:
    result = LinkSyncResult(status="synced")
    removed_shas: list[str] = []
    stale_link_names: list[str] = []
    link_states: LinkStates = []
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
            result = LinkSyncResult(
                status="unchanged", pages=gallery.pages, pending=await _pending_count(session, gallery_id)
            )
        else:
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
            renames = pair_renames(plan.missing, plan.new)
            renamed_ids = {image.image_id for image, _ in renames}
            renamed_paths = {file.path for _, file in renames}
            missing = [image for image in plan.missing if image.image_id not in renamed_ids]
            new_files = await asyncio.to_thread(
                _valid_media, [file for file in plan.new if file.path not in renamed_paths]
            )
            max_page = max((row.page_num for row in rows), default=0)

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

                # 2. Renames keep the Image row, and its blob if it has one. The
                # composite FK (blob_sha256, external_path) is not deferrable, so
                # the new location must exist before the image points at it.
                for image, file in renames:
                    if image.sha256 is not None:
                        await session.execute(
                            pg_insert(BlobLocation)
                            .values(blob_sha256=image.sha256, external_path=file.path)
                            .on_conflict_do_nothing(index_elements=["blob_sha256", "external_path"])
                        )
                    await session.execute(
                        update(Image)
                        .where(Image.id == image.image_id)
                        .values(external_path=file.path, filename=file.name)
                    )
                    await _expose(source, source_id, file.name, file.path, link_states)
                    stale_link_names.append(Path(image.external_path).name)
                    result.renamed += 1

                # 3. New files become pending pages: readable now, hashed later.
                if new_files:
                    now = datetime.now(UTC)
                    await session.execute(
                        insert(Image),
                        [
                            {
                                "gallery_id": gallery_id,
                                "page_num": max_page + offset,
                                "filename": file.name,
                                "blob_sha256": None,
                                "external_path": file.path,
                                "source_size": file.size,
                                "source_mtime_ns": file.mtime_ns,
                                "added_at": now,
                            }
                            for offset, file in enumerate(new_files, start=1)
                        ],
                    )
                    for file in new_files:
                        await _expose(source, source_id, file.name, file.path, link_states)
                    result.added = len(new_files)

                # 4. A changed file loses its blob and waits for the next hash pass.
                # Blob statements come first: lock order is blobs -> images -> galleries.
                for image, file in plan.changed:
                    if image.sha256 is not None:
                        await decrement_ref_count(image.sha256, session)
                        removed_shas.append(image.sha256)
                    await session.execute(
                        update(Image)
                        .where(Image.id == image.image_id)
                        .values(blob_sha256=None, source_size=file.size, source_mtime_ns=file.mtime_ns)
                    )
                    result.replaced += 1

                # 5. Files that are gone and were not a rename.
                for image in missing:
                    if image.sha256 is not None:
                        await decrement_ref_count(image.sha256, session)
                        removed_shas.append(image.sha256)
                    await session.execute(delete(Image).where(Image.id == image.image_id))
                    stale_link_names.append(Path(image.external_path).name)
                    result.removed += 1

                # 6. Gallery bookkeeping, last: lock order is blobs -> galleries,
                # and these ORM changes only flush at commit.
                pages = await _active_page_count(session, gallery_id)
                pending = await _pending_count(session, gallery_id)
                gallery.pages = pages
                if pages == 0 and gallery.download_status != "importing":
                    gallery.download_status = "missing"
                elif pages > 0 and gallery.download_status == "missing":
                    gallery.download_status = "complete"
                # Only a pass with no unsettled file may arm the directory-mtime shortcut.
                gallery.source_dir_mtime_ns = dir_mtime_ns if not plan.unsettled else None
                gallery.last_scanned_at = datetime.now(UTC)
                if result.changed:
                    gallery.metadata_updated_at = func.now()
                    sidecar_payload = sidecar_payload_from_gallery(gallery)
                await _commit(session, link_states)
            except Exception:
                _restore_links(link_states)
                raise

            result.pages, result.pending, result.unsettled = pages, pending, len(plan.unsettled)
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
    if result.pending:
        await enqueue_link_hash(gallery_id)
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
