"""Full library rescan job."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.sql import select

import core.queue
from core.database import AsyncSessionLocal
from db.models import Gallery, Image
from services.cas import decrement_ref_count, resolve_blob_path
from services.link_sync import library_root_available
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails
from worker.constants import logger
from worker.scan_common import _cover_image_for_gallery, _has_thumb_160, _probe_pages
from worker.scan_vanished import _announce_vanished_link_galleries, _hold_vanished_link_gallery, _link_source_vanished


async def rescan_library_job(ctx: dict) -> dict:
    """
    Rescan all galleries in the database:
    - Verify image files still exist on disk; remove DB records for missing files.
    - Update gallery.pages to the actual file count.
    - Enqueue thumbnail_job for galleries with images that have no thumbnail.
    Progress is written to Redis key ``rescan:progress`` during the run and
    deleted on completion so the status endpoint can report accurately.

    Batch processing: galleries are processed in chunks of 500 to avoid the
    N+1 query problem that arises with per-gallery SELECT FROM images.
    """
    import json as _json
    from collections import Counter, defaultdict

    from sqlalchemy.orm import selectinload

    logger.info("[rescan_library] starting full library rescan")
    r = ctx["redis"]

    # Pause watcher during full rescan to avoid duplicate triggers
    from core.watcher import watcher_instance as _wi

    _watcher_was_running = _wi is not None and _wi.is_running
    if _watcher_was_running:
        _wi.pause()

    total = 0
    cancelled = False
    try:
        async with AsyncSessionLocal() as session:
            # Fetch only IDs ordered by scan priority (unscanned first)
            # Exclude soft-deleted (trashed) galleries — edge case #95
            all_gallery_ids = (
                (
                    await session.execute(
                        select(Gallery.id)
                        .where(Gallery.deleted_at.is_(None))
                        .order_by(Gallery.last_scanned_at.asc().nulls_first())
                    )
                )
                .scalars()
                .all()
            )
            total = len(all_gallery_ids)
            logger.info("[rescan_library] %d galleries to scan", total)

            CHUNK = 500
            processed = 0
            pending_thumbnail_galleries: list[int] = []
            root_available: dict[str, bool] = {}

            for chunk_start in range(0, total, CHUNK):
                # Check for cancel signal once per chunk
                cancel_flag = await r.get("rescan:cancel")
                if cancel_flag:
                    await r.delete("rescan:cancel")
                    await r.setex(
                        "rescan:progress",
                        3600,
                        _json.dumps({"processed": processed, "total": total, "status": "cancelled"}),
                    )
                    logger.info("[rescan_library] cancelled at %d/%d", processed, total)
                    cancelled = True
                    break

                chunk_ids = all_gallery_ids[chunk_start : chunk_start + CHUNK]

                # Batch load all images + blobs for this chunk in a single query
                images_result = (
                    (
                        await session.execute(
                            select(Image)
                            .where(Image.gallery_id.in_(chunk_ids))
                            .order_by(Image.gallery_id.asc(), Image.page_num.asc())
                            .options(selectinload(Image.blob))
                        )
                    )
                    .scalars()
                    .all()
                )

                # Group images by gallery_id
                images_by_gallery: dict[int, list] = defaultdict(list)
                for img in images_result:
                    images_by_gallery[img.gallery_id].append(img)

                # Batch load Gallery ORM objects for this chunk
                galleries = (await session.execute(select(Gallery).where(Gallery.id.in_(chunk_ids)))).scalars().all()
                gallery_map = {g.id: g for g in galleries}

                # Accumulate batch operations across the chunk
                shas_to_decrement: list[str] = []
                images_to_delete: list[int] = []
                galleries_to_delete: list[int] = []
                galleries_needing_thumbs: list[int] = []
                galleries_needing_cover_thumbs: list[int] = []
                vanished_outcomes: list[tuple[int, str]] = []

                for gid in chunk_ids:
                    # The checks below are synchronous filesystem calls. Yield
                    # so imports and syncs sharing this worker are not starved.
                    await asyncio.sleep(0)
                    gallery = gallery_map.get(gid)
                    if not gallery:
                        continue

                    # An unmounted or empty library root makes every link file
                    # look deleted. Fail closed: skip verification, remove nothing.
                    if gallery.import_mode == "link" and gallery.library_path:
                        root = gallery.library_path
                        if root not in root_available:
                            root_available[root] = library_root_available(root)
                            if not root_available[root]:
                                logger.error(
                                    "[rescan_library] library root %s is missing or empty; skipping its link galleries",
                                    root,
                                )
                        if not root_available[root]:
                            continue

                    images = images_by_gallery.get(gid, [])
                    if _link_source_vanished(gallery, images):
                        outcome = _hold_vanished_link_gallery(gallery)
                        if outcome:
                            vanished_outcomes.append((gid, outcome))
                        continue

                    missing_thumb = False
                    missing_cover_thumb = False
                    removed = 0
                    cover_image = _cover_image_for_gallery(gallery, images)
                    existing_images_for_cover: list[Image] = []

                    for img, (file_exists, has_thumb) in zip(images, await _probe_pages(images), strict=True):
                        blob = img.blob
                        if not blob:
                            if img.external_path:
                                # Pending link page: registered from the folder
                                # but not hashed yet, so it has no blob. It is
                                # live data; only a vanished file removes it,
                                # and there is no blob ref_count to give back.
                                if file_exists:
                                    existing_images_for_cover.append(img)
                                    continue
                                logger.warning(
                                    "[rescan_library] gallery_id=%d image_id=%d missing pending file: %s",
                                    gid,
                                    img.id,
                                    img.external_path,
                                )
                            # No blob and no file to serve it from is an orphan row.
                            images_to_delete.append(img.id)
                            removed += 1
                            continue
                        if not file_exists:
                            logger.warning(
                                "[rescan_library] gallery_id=%d image_id=%d missing file: %s",
                                gid,
                                img.id,
                                str(resolve_blob_path(blob, img.external_path)),
                            )
                            shas_to_decrement.append(blob.sha256)
                            images_to_delete.append(img.id)
                            removed += 1
                            continue
                        existing_images_for_cover.append(img)
                        if not has_thumb:
                            missing_thumb = True
                            if img is cover_image:
                                missing_cover_thumb = True

                    if removed:
                        gallery.pages = len(images) - removed
                        if gallery.pages == 0 and gallery.import_mode == "link":
                            # Mark for bulk delete — gallery row + its images handled via cascade
                            galleries_to_delete.append(gid)
                            logger.info(
                                "[rescan_library] gallery_id=%d marked for removal (link mode, all files gone)",
                                gid,
                            )
                            continue  # skip last_scanned_at update for this gallery
                        elif gallery.pages == 0:
                            gallery.download_status = "missing"
                        logger.info(
                            "[rescan_library] gallery_id=%d: removed %d missing images, pages=%d",
                            gid,
                            removed,
                            gallery.pages,
                        )

                    if missing_thumb and not missing_cover_thumb:
                        current_cover = _cover_image_for_gallery(gallery, existing_images_for_cover)
                        if (
                            current_cover
                            and current_cover.blob
                            and not await asyncio.to_thread(_has_thumb_160, current_cover.blob)
                        ):
                            missing_cover_thumb = True

                    if missing_thumb:
                        galleries_needing_thumbs.append(gid)
                    if missing_cover_thumb:
                        galleries_needing_cover_thumbs.append(gid)

                    gallery.last_scanned_at = datetime.now(UTC)

                # ── Batch DB operations for this chunk ──────────────────────

                # Batch decrement blob ref_counts, accounting for multiple
                # images referencing the same sha (each missing image = -1).
                if shas_to_decrement:
                    sha_counts = Counter(shas_to_decrement)
                    # Lock order must be blobs → galleries, the same as the
                    # importer and the link sync. The loop above left gallery
                    # updates (pages, last_scanned_at) pending; autoflush would
                    # send them before the first ref_count UPDATE and lock
                    # gallery rows first. An import holding a blob lock that
                    # then updates its own gallery row deadlocks with that.
                    with session.no_autoflush:
                        for sha256, count in sha_counts.items():
                            await decrement_ref_count(sha256, session, count)

                # Send the pending gallery updates now: after the blob updates
                # (lock order), and before the raw DELETEs below. Textual
                # statements do not autoflush and the ORM cannot see them
                # delete a gallery row, so an update still pending for that
                # row would fail the commit with StaleDataError.
                await session.flush()

                # Batch delete orphaned/missing images
                if images_to_delete:
                    await session.execute(
                        text("DELETE FROM images WHERE id = ANY(:ids)"),
                        {"ids": images_to_delete},
                    )

                # Batch delete zero-page link-mode galleries (cascade removes images)
                if galleries_to_delete:
                    await session.execute(
                        text("DELETE FROM galleries WHERE id = ANY(:ids)"),
                        {"ids": galleries_to_delete},
                    )

                await session.commit()

                if shas_to_decrement:
                    await cleanup_unreferenced_thumbnails(session, shas_to_decrement)
                if vanished_outcomes:
                    await _announce_vanished_link_galleries(vanished_outcomes)

                # Enqueue thumbnail jobs outside the transaction
                for gid in galleries_needing_cover_thumbs:
                    await core.queue.enqueue(
                        "cover_thumbnail_job",
                        gallery_id=gid,
                        _timeout=300,
                        _job_id=f"cover-thumbnail:{gid}",
                    )
                    logger.info(
                        "[rescan_library] gallery_id=%d: enqueued cover_thumbnail_job (missing cover thumb)",
                        gid,
                    )
                pending_thumbnail_galleries.extend(galleries_needing_thumbs)

                processed += len(chunk_ids)
                await r.setex(
                    "rescan:progress",
                    3600,
                    _json.dumps({"processed": processed, "total": total, "status": "running"}),
                )

            if not cancelled:
                for gid in pending_thumbnail_galleries:
                    await core.queue.enqueue(
                        "thumbnail_job",
                        gallery_id=gid,
                        _timeout=3600,
                        _job_id=f"thumbnail:{gid}",
                    )
                    logger.info(
                        "[rescan_library] gallery_id=%d: enqueued thumbnail_job (missing thumbs)",
                        gid,
                    )

    finally:
        # Always resume the watcher even if the scan fails or is cancelled
        if _watcher_was_running and _wi is not None:
            _wi.resume()

    if not cancelled:
        await r.setex(
            "rescan:progress",
            30,
            _json.dumps({"processed": total, "total": total, "status": "done"}),
        )
        logger.info("[rescan_library] completed, %d galleries processed", total)

        from core.events import EventType, emit_safe

        await emit_safe(EventType.RESCAN_COMPLETED, resource_type="system", total=total)

    return {"status": "cancelled" if cancelled else "done", "total": total}
