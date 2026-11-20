"""Single gallery rescan job."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.sql import select

import core.queue
from core.database import AsyncSessionLocal
from core.source_display import get_display_config
from db.models import ExcludedBlob, Gallery, Image
from services.cas import (
    create_library_symlink,
    decrement_ref_count,
    increment_ref_count,
    library_dir,
    resolve_blob_path,
    store_blob,
)
from services.link_sync import library_root_available, sync_link_gallery
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails
from worker.constants import logger
from worker.helpers import _sha256
from worker.scan_common import _cover_image_for_gallery, _has_thumb_160, _list_media_files, _probe_pages
from worker.scan_vanished import _announce_vanished_link_galleries, _hold_vanished_link_gallery, _link_source_vanished


async def rescan_gallery_job(ctx: dict, gallery_id: int) -> dict:
    """
    Rescan a single gallery:
    - Verify existing image files; remove DB records for files that have gone missing.
    - Scan the gallery directory for new files not yet in the DB and insert them.
    - Update gallery.pages and gallery.download_status.
    - Re-enqueue thumbnail_job if any thumbnails are absent.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert_local

    logger.info("[rescan_gallery] gallery_id=%d", gallery_id)

    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if not gallery:
            logger.error("[rescan_gallery] gallery_id=%d not found", gallery_id)
            return {"status": "failed", "error": "gallery not found"}

        # Edge case #58: never mutate a trashed (soft-deleted) gallery. A
        # rescan would delete images, renumber pages, or regenerate thumbnails
        # before trash retention expires, weakening trash reversibility. This
        # is the central guard for every entry point (watcher rescan_by_path,
        # manual rescan, library-path rescan). Only trash GC may mutate trash.
        if gallery.deleted_at is not None:
            logger.info("[rescan_gallery] gallery_id=%d is trashed; skipping", gallery_id)
            return {"status": "skipped", "reason": "trashed"}

        if gallery.import_mode == "link" and gallery.source_path and Path(gallery.source_path).is_dir():
            # A link gallery with a live source directory uses the stat-only
            # fingerprint sync (new files become pending pages, hashed later by
            # link_hash_job). A vanished source directory continues below, where
            # it is held unless some page file is still readable.
            await session.rollback()  # release the snapshot before the sync opens its own session
            sync_result = await sync_link_gallery(gallery_id, redis=ctx["redis"], force=True)
            return {
                "status": "done" if sync_result.status in ("synced", "unchanged") else sync_result.status,
                "gallery_id": gallery_id,
                "removed": sync_result.removed,
                "added": sync_result.added,
                "pages": sync_result.pages,
            }
        if gallery.import_mode == "link" and not library_root_available(gallery.library_path):
            logger.error("[rescan_gallery] gallery_id=%d: library root unavailable; nothing removed", gallery_id)
            return {"status": "skipped", "reason": "root_unavailable"}

        # Load excluded blob hashes for this gallery
        excluded_rows = (
            (await session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
            .scalars()
            .all()
        )
        excluded_set: set[str] = set(excluded_rows)

        from sqlalchemy.orm import selectinload

        images = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.asc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

        if _link_source_vanished(gallery, images):
            outcome = _hold_vanished_link_gallery(gallery)
            await session.commit()
            if outcome:
                await _announce_vanished_link_galleries([(gallery_id, outcome)])
            return {
                "status": "source_missing",
                "gallery_id": gallery_id,
                "removed": 0,
                "added": 0,
                "pages": gallery.pages,
            }

        # --- Step 1: Verify existing records ---
        known_sha256s: set[str] = set()
        pending_paths: set[str] = set()
        missing_thumb = False
        missing_cover_thumb = False
        removed = 0
        removed_blob_sha256s: list[str] = []
        cover_image = _cover_image_for_gallery(gallery, images, excluded_set)
        for img, (file_exists, has_thumb) in zip(images, await _probe_pages(images), strict=True):
            blob = img.blob
            if not blob:
                if img.external_path and file_exists:
                    # Pending link page (not hashed yet): live data, keep it.
                    pending_paths.add(img.external_path)
                    continue
                # A pending page whose file is gone, or a row with neither a
                # blob nor a file, is removed. Neither holds a blob reference.
                await session.delete(img)
                removed += 1
                continue
            if not file_exists:
                logger.warning(
                    "[rescan_gallery] gallery_id=%d image_id=%d missing: %s",
                    gallery_id,
                    img.id,
                    str(resolve_blob_path(blob, img.external_path)),
                )
                await decrement_ref_count(blob.sha256, session)
                removed_blob_sha256s.append(blob.sha256)
                await session.delete(img)
                removed += 1
                continue
            known_sha256s.add(blob.sha256)
            if not has_thumb:
                missing_thumb = True
                if img is cover_image:
                    missing_cover_thumb = True

        if removed:
            await session.flush()

        # --- Step 2: Discover new files in the gallery directory ---
        # CAS/copy galleries scan the library symlink directory. Link-mode
        # monitored galleries scan their original external source directory.
        gallery_dir: Path | None = None
        surviving_images = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.asc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

        if gallery.import_mode == "link" and gallery.source_path:
            source_dir = Path(gallery.source_path)
            if source_dir.exists():
                gallery_dir = source_dir
        if gallery_dir is None:
            symlink_dir = library_dir(gallery.source, gallery.source_id)
            if symlink_dir.exists():
                gallery_dir = symlink_dir

        new_files_added = 0
        if gallery_dir and gallery_dir.is_dir():
            # Determine the next page_num
            max_page = max((img.page_num for img in surviving_images), default=0)

            try:
                dir_files = sorted(await asyncio.to_thread(_list_media_files, gallery_dir), key=lambda f: f.name)
            except OSError as exc:
                logger.warning("[rescan_gallery] gallery_id=%d failed to read dir: %s", gallery_id, exc)
                dir_files = []

            for fpath in dir_files:
                # A pending page has no sha to match on, so recognise its file
                # by path (directly or through the library symlink); otherwise
                # it would be registered a second time.
                if pending_paths and (str(fpath) in pending_paths or os.path.realpath(fpath) in pending_paths):
                    continue
                file_hash = await asyncio.to_thread(_sha256, fpath)
                if file_hash in known_sha256s:
                    continue
                if file_hash in excluded_set:
                    logger.debug(
                        "[rescan_gallery] gallery_id=%d: skipping excluded blob %s (%s)",
                        gallery_id,
                        file_hash[:12],
                        fpath.name,
                    )
                    continue
                # New file found on disk that is not in the DB.
                if gallery.import_mode == "link":
                    image_external_path = str(fpath)
                    blob = await store_blob(
                        fpath,
                        file_hash,
                        session,
                        storage="external",
                        external_path=image_external_path,
                    )
                else:
                    image_external_path = None
                    blob = await store_blob(fpath, file_hash, session)
                await create_library_symlink(
                    gallery.source,
                    gallery.source_id,
                    fpath.name,
                    blob,
                    external_path=image_external_path,
                )
                await session.flush()
                max_page += 1
                stmt = (
                    pg_insert_local(Image)
                    .values(
                        gallery_id=gallery_id,
                        page_num=max_page,
                        filename=fpath.name,
                        blob_sha256=file_hash,
                        external_path=image_external_path,
                    )
                    .on_conflict_do_nothing()
                    .returning(Image.id)
                )
                result = await session.execute(stmt)
                inserted = result.scalar_one_or_none()

                if inserted is not None:
                    # New Image row created — increment blob ref_count.
                    await increment_ref_count(file_hash, session)
                new_files_added += 1
                missing_thumb = True  # New file needs a thumbnail.
                if max_page == 1 or get_display_config(gallery.source or "").cover_page == "last":
                    missing_cover_thumb = True
                known_sha256s.add(file_hash)
                logger.info(
                    "[rescan_gallery] gallery_id=%d: added new file %s",
                    gallery_id,
                    fpath.name,
                )

        # --- Step 3: Update gallery metadata ---
        final_images = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.asc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )
        gallery.pages = len(final_images)
        if missing_thumb and not missing_cover_thumb:
            current_cover = _cover_image_for_gallery(gallery, final_images, excluded_set)
            if current_cover and current_cover.blob and not _has_thumb_160(current_cover.blob):
                missing_cover_thumb = True

        if gallery.pages == 0 and gallery.import_mode == "link":
            # All source files are gone — clean up blob references. Shared
            # thumbnails are removed only after the committed Image changes.
            # Use final_images (already queried above) — re-querying returns empty because
            # images were deleted in Step 1 and flushed, causing the blob leak.
            for rim in final_images:
                if rim.blob:
                    await decrement_ref_count(rim.blob.sha256, session)
                    removed_blob_sha256s.append(rim.blob.sha256)
            await session.delete(gallery)
            await session.commit()
            await cleanup_unreferenced_thumbnails(session, removed_blob_sha256s)
            logger.info("[rescan_gallery] gallery_id=%d removed (link mode, all files gone)", gallery_id)
            return {"status": "removed", "gallery_id": gallery_id, "removed": removed, "added": 0, "pages": 0}

        if gallery.pages == 0:
            gallery.download_status = "missing"
        elif gallery.download_status == "missing":
            gallery.download_status = "complete"
        gallery.last_scanned_at = datetime.now(UTC)

        await session.commit()

        if removed_blob_sha256s:
            await cleanup_unreferenced_thumbnails(session, removed_blob_sha256s)

    if missing_thumb:
        if missing_cover_thumb:
            await core.queue.enqueue(
                "cover_thumbnail_job",
                gallery_id=gallery_id,
                _timeout=300,
                _job_id=f"cover-thumbnail:{gallery_id}",
            )
            logger.info("[rescan_gallery] gallery_id=%d: enqueued cover_thumbnail_job", gallery_id)
        await core.queue.enqueue(
            "thumbnail_job",
            gallery_id=gallery_id,
            _timeout=3600,
            _job_id=f"thumbnail:{gallery_id}",
        )
        logger.info("[rescan_gallery] gallery_id=%d: enqueued thumbnail_job", gallery_id)

    logger.info(
        "[rescan_gallery] gallery_id=%d done: removed=%d added=%d pages=%d",
        gallery_id,
        removed,
        new_files_added,
        gallery.pages,
    )
    return {
        "status": "done",
        "gallery_id": gallery_id,
        "removed": removed,
        "added": new_files_added,
        "pages": gallery.pages,
    }
