"""Library scan and rescan jobs for the worker package."""

import asyncio
import json
import os
from datetime import UTC, datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import get_all_library_paths, settings
from core.database import AsyncSessionLocal
from db.models import Blob, ExcludedBlob, Gallery, Image
from services.cas import (
    create_library_symlink,
    decrement_ref_count,
    library_dir,
    resolve_blob_path,
    store_blob,
    thumb_dir,
)
from worker.constants import _IMAGE_EXTS, _MEDIA_EXTS, _VIDEO_EXTS, logger
from worker.helpers import _cron_record, _cron_should_run, _sha256, _validate_image_magic

_SUPPORTED_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}


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
    import shutil
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
            all_gallery_ids = (await session.execute(
                select(Gallery.id).order_by(Gallery.last_scanned_at.asc().nulls_first())
            )).scalars().all()
            total = len(all_gallery_ids)
            logger.info("[rescan_library] %d galleries to scan", total)

            CHUNK = 500
            processed = 0

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

                chunk_ids = all_gallery_ids[chunk_start:chunk_start + CHUNK]

                # Batch load all images + blobs for this chunk in a single query
                images_result = (await session.execute(
                    select(Image)
                    .where(Image.gallery_id.in_(chunk_ids))
                    .options(selectinload(Image.blob))
                )).scalars().all()

                # Group images by gallery_id
                images_by_gallery: dict[int, list] = defaultdict(list)
                for img in images_result:
                    images_by_gallery[img.gallery_id].append(img)

                # Batch load Gallery ORM objects for this chunk
                galleries = (await session.execute(
                    select(Gallery).where(Gallery.id.in_(chunk_ids))
                )).scalars().all()
                gallery_map = {g.id: g for g in galleries}

                # Accumulate batch operations across the chunk
                shas_to_decrement: list[str] = []
                images_to_delete: list[int] = []
                galleries_to_delete: list[int] = []
                galleries_needing_thumbs: list[int] = []

                for gid in chunk_ids:
                    gallery = gallery_map.get(gid)
                    if not gallery:
                        continue

                    images = images_by_gallery.get(gid, [])
                    missing_thumb = False
                    removed = 0

                    for img in images:
                        blob = img.blob
                        if not blob:
                            images_to_delete.append(img.id)
                            removed += 1
                            continue
                        src = resolve_blob_path(blob)
                        if not src.exists():
                            logger.warning(
                                "[rescan_library] gallery_id=%d image_id=%d missing file: %s",
                                gid,
                                img.id,
                                str(src),
                            )
                            # Remove thumbnail directory immediately (filesystem op)
                            td = thumb_dir(blob.sha256)
                            if td.exists():
                                shutil.rmtree(str(td), ignore_errors=True)
                            shas_to_decrement.append(blob.sha256)
                            images_to_delete.append(img.id)
                            removed += 1
                            continue
                        td = thumb_dir(blob.sha256)
                        if not (td / "thumb_160.webp").exists():
                            missing_thumb = True

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

                    if missing_thumb:
                        galleries_needing_thumbs.append(gid)

                    gallery.last_scanned_at = datetime.now(timezone.utc)

                # ── Batch DB operations for this chunk ──────────────────────

                # Batch decrement blob ref_counts, accounting for multiple
                # images referencing the same sha (each missing image = -1).
                if shas_to_decrement:
                    sha_counts = Counter(shas_to_decrement)
                    unique_shas = list(sha_counts.keys())
                    decrements = [sha_counts[s] for s in unique_shas]
                    await session.execute(
                        text("""
                            UPDATE blobs SET ref_count = ref_count - v.n
                            FROM (SELECT unnest(:shas::text[]) AS sha,
                                         unnest(:ns::int[])  AS n) v
                            WHERE blobs.sha256 = v.sha
                        """),
                        {"shas": unique_shas, "ns": decrements},
                    )

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

                # Enqueue thumbnail jobs outside the transaction
                for gid in galleries_needing_thumbs:
                    await r.enqueue_job("thumbnail_job", gid)
                    logger.info(
                        "[rescan_library] gallery_id=%d: enqueued thumbnail_job (missing thumbs)",
                        gid,
                    )

                processed += len(chunk_ids)
                await r.setex(
                    "rescan:progress",
                    3600,
                    _json.dumps({"processed": processed, "total": total, "status": "running"}),
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

        # Load excluded blob hashes for this gallery
        excluded_rows = (await session.execute(
            select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)
        )).scalars().all()
        excluded_set: set[str] = set(excluded_rows)

        import shutil
        from sqlalchemy.orm import selectinload
        images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        # --- Step 1: Verify existing records ---
        known_sha256s: set[str] = set()
        missing_thumb = False
        removed = 0
        for img in images:
            blob = img.blob
            if not blob:
                await session.delete(img)
                removed += 1
                continue
            src = resolve_blob_path(blob)
            if not src.exists():
                logger.warning(
                    "[rescan_gallery] gallery_id=%d image_id=%d missing: %s",
                    gallery_id,
                    img.id,
                    str(src),
                )
                # Delete thumbnail directory before removing the DB record
                td = thumb_dir(blob.sha256)
                if td.exists():
                    shutil.rmtree(str(td), ignore_errors=True)
                await decrement_ref_count(blob.sha256, session)
                await session.delete(img)
                removed += 1
                continue
            known_sha256s.add(blob.sha256)
            td = thumb_dir(blob.sha256)
            if not (td / "thumb_160.webp").exists():
                missing_thumb = True

        if removed:
            await session.flush()

        # --- Step 2: Discover new files in the gallery directory ---
        # With CAS, the gallery directory is the library symlink directory.
        gallery_dir: Path | None = None
        surviving_images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        gallery_dir = library_dir(gallery.source, gallery.source_id)
        if not gallery_dir.exists():
            gallery_dir = None

        new_files_added = 0
        if gallery_dir and gallery_dir.is_dir():
            _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}
            # Determine the next page_num
            max_page = max((img.page_num for img in surviving_images), default=0)

            try:
                dir_files = sorted(
                    [f for f in gallery_dir.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS],
                    key=lambda f: f.name,
                )
            except OSError as exc:
                logger.warning("[rescan_gallery] gallery_id=%d failed to read dir: %s", gallery_id, exc)
                dir_files = []

            for fpath in dir_files:
                file_hash = await asyncio.to_thread(_sha256, fpath)
                if file_hash in known_sha256s:
                    continue
                if file_hash in excluded_set:
                    logger.debug(
                        "[rescan_gallery] gallery_id=%d: skipping excluded blob %s (%s)",
                        gallery_id, file_hash[:12], fpath.name,
                    )
                    continue
                # New file found on disk that is not in the DB.
                blob = await store_blob(fpath, file_hash, session)
                await create_library_symlink(gallery.source, gallery.source_id, fpath.name, blob)
                await session.flush()
                max_page += 1
                stmt = pg_insert_local(Image).values(
                    gallery_id=gallery_id,
                    page_num=max_page,
                    filename=fpath.name,
                    blob_sha256=file_hash,
                ).on_conflict_do_nothing()
                await session.execute(stmt)
                new_files_added += 1
                missing_thumb = True  # New file needs a thumbnail.
                known_sha256s.add(file_hash)
                logger.info(
                    "[rescan_gallery] gallery_id=%d: added new file %s",
                    gallery_id,
                    fpath.name,
                )

        # --- Step 3: Update gallery metadata ---
        final_images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()
        gallery.pages = len(final_images)

        if gallery.pages == 0 and gallery.import_mode == "link":
            # All source files are gone — clean up blob ref-counts and thumbnail dirs
            # Use final_images (already queried above) — re-querying returns empty because
            # images were deleted in Step 1 and flushed, causing the blob leak.
            for rim in final_images:
                if rim.blob:
                    td = thumb_dir(rim.blob.sha256)
                    if td.exists():
                        shutil.rmtree(str(td), ignore_errors=True)
                    await decrement_ref_count(rim.blob.sha256, session)
            await session.delete(gallery)
            await session.commit()
            logger.info("[rescan_gallery] gallery_id=%d removed (link mode, all files gone)", gallery_id)
            return {"status": "removed", "gallery_id": gallery_id, "removed": removed, "added": 0, "pages": 0}

        if gallery.pages == 0:
            gallery.download_status = "missing"
        elif gallery.download_status == "missing":
            gallery.download_status = "complete"
        gallery.last_scanned_at = datetime.now(timezone.utc)

        await session.commit()

    if missing_thumb:
        await ctx["redis"].enqueue_job("thumbnail_job", gallery_id)
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


async def auto_discover_job(ctx: dict) -> dict:
    """Scan all library paths recursively and auto-create galleries for undiscovered directories containing media files."""
    logger.info("[auto_discover] Starting auto-discovery")

    paths = await get_all_library_paths()

    discovered = 0
    async with AsyncSessionLocal() as session:
        # Get all existing source="local" galleries with their source_id and library_path
        existing_rows = (await session.execute(
            select(Gallery.source_id, Gallery.library_path).where(Gallery.source == "local")
        )).all()
        existing_set = {(row.source_id, row.library_path) for row in existing_rows}

        for lib_path in paths:
            lib_dir = Path(lib_path)
            if not lib_dir.is_dir():
                continue

            # Walk the directory tree recursively; os.walk is efficient for deep trees
            for dirpath, dirnames, filenames in os.walk(str(lib_dir)):
                # Skip hidden directories in-place so os.walk won't descend into them
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

                current = Path(dirpath)
                # Skip the library root itself — only subfolders are gallery candidates
                if current == lib_dir:
                    continue

                # Use path relative to the library root as source_id for uniqueness
                # (e.g. "artist/album" instead of just "album" to avoid collisions)
                try:
                    rel_path = str(current.relative_to(lib_dir))
                except ValueError:
                    continue

                if (rel_path, lib_path) in existing_set:
                    continue

                # Only create a gallery if the directory directly contains media files
                file_count = sum(
                    1 for f in filenames
                    if Path(f).suffix.lower() in _SUPPORTED_MEDIA_EXTS
                )
                if file_count == 0:
                    continue

                # Derive a human-readable title from the leaf directory name
                title = current.name

                result = await session.execute(
                    text(
                        "INSERT INTO galleries (source, source_id, title, library_path, download_status)"
                        " VALUES ('local', :source_id, :title, :lib_path, 'importing')"
                        " ON CONFLICT (source, source_id) DO NOTHING"
                        " RETURNING id"
                    ),
                    {"source_id": rel_path, "title": title, "lib_path": lib_path},
                )
                row = result.scalar_one_or_none()
                if row:
                    gallery_id = row
                    discovered += 1
                    logger.info("[auto_discover] New gallery: %s (%d files)", rel_path, file_count)
                    await ctx["redis"].enqueue_job("local_import_job", str(current), "link", gallery_id)

        await session.commit()

    logger.info("[auto_discover] Discovered %d new galleries", discovered)

    from core.events import EventType, emit_safe
    await emit_safe(EventType.GALLERY_DISCOVERED, resource_type="gallery", discovered=discovered)

    return {"discovered": discovered}


async def rescan_by_path_job(ctx: dict, dir_path: str) -> dict:
    """Rescan the gallery whose files reside in dir_path."""
    # In CAS mode, /data/library/{gallery_id}/ is the gallery directory.
    lib_base = Path(settings.data_library_path)
    dir_p = Path(dir_path)

    gallery_id: int | None = None
    # Check if this path is a library directory (or inside one).
    # Library structure is lib_base/source/source_id/.
    try:
        rel = dir_p.relative_to(lib_base)
        if len(rel.parts) >= 2:
            source = rel.parts[0]
            source_id = rel.parts[1]
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Gallery.id).where(Gallery.source == source, Gallery.source_id == source_id)
                )
                gallery_id = result.scalar_one_or_none()
    except (ValueError, IndexError):
        pass

    if not gallery_id:
        # Try checking if it's a blob external path
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Image.gallery_id)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .where(Blob.external_path.like(
                    dir_path.replace('%', '\\%').replace('_', '\\_') + '%',
                    escape='\\',
                ))
                .limit(1)
            )
            gallery_id = result.scalar_one_or_none()

    if gallery_id:
        return await rescan_gallery_job(ctx, gallery_id)

    # No existing gallery found — might be a new directory, trigger auto-discover
    await ctx["redis"].enqueue_job("auto_discover_job")
    return {"status": "no_gallery_found", "path": dir_path}


async def rescan_library_path_job(ctx: dict, library_path: str) -> dict:
    """Rescan all galleries that belong to a specific library path."""
    import json as _json

    logger.info("[rescan_path] starting rescan for path: %s", library_path)
    r = ctx["redis"]

    async with AsyncSessionLocal() as session:
        # Find all galleries with this library_path or whose images are under this path
        gallery_rows = (await session.execute(
            select(Gallery).where(
                (Gallery.library_path == library_path) |
                (Gallery.source == "local")
            ).order_by(Gallery.id)
        )).scalars().all()

        # Filter to galleries actually under this path
        relevant = []
        for g in gallery_rows:
            if g.library_path == library_path:
                relevant.append(g)
            elif g.library_path is None and g.import_mode == "link":
                # Check if any blob has external_path under this library_path
                blob_row = (await session.execute(
                    select(Blob.external_path)
                    .join(Image, Image.blob_sha256 == Blob.sha256)
                    .where(Image.gallery_id == g.id, Blob.storage == "external")
                    .limit(1)
                )).scalar_one_or_none()
                if blob_row and blob_row.startswith(library_path):
                    relevant.append(g)

        total = len(relevant)
        logger.info("[rescan_path] %d galleries under %s", total, library_path)

    # Rescan each gallery using existing job logic
    for idx, gallery in enumerate(relevant):
        await r.setex("rescan:progress", 3600, _json.dumps({
            "processed": idx, "total": total, "status": "running",
            "current_gallery": gallery.id,
        }))
        await rescan_gallery_job(ctx, gallery.id)

    await r.setex("rescan:progress", 30, _json.dumps({
        "processed": total, "total": total, "status": "done",
    }))
    logger.info("[rescan_path] completed, %d galleries processed", total)
    return {"status": "done", "total": total}


async def scheduled_scan_job(ctx: dict) -> dict:
    """Scheduled library scan — uses croniter-based gating."""
    if not await _cron_should_run(ctx, "library_scan", "0 * * * *"):
        return {"status": "skipped"}

    try:
        await _cron_record(ctx, "library_scan", "running")
        logger.info("[scheduled_scan] Starting scheduled library scan")
        await auto_discover_job(ctx)
        await rescan_library_job(ctx)
        await _cron_record(ctx, "library_scan", "ok")
        logger.info("[scheduled_scan] Scheduled scan complete")
        return {"status": "done"}
    except Exception as exc:
        await _cron_record(ctx, "library_scan", "failed", str(exc))
        raise
