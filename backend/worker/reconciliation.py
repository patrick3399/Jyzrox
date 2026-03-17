"""Reconciliation job for the worker package."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text, tuple_
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import Blob, Gallery, Image
from services.cas import cas_path, thumb_dir
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run


async def reconciliation_job(ctx: dict) -> dict:
    """
    Reconcile /data/library/ symlink tree with database records.

    Users can delete symlinks directly from filesystem. This job syncs
    those changes back to the database.

    Also runs blob GC: removes unreferenced blobs and their CAS files.

    Batch-optimised for 10M images / 100K galleries:
    - Phase 1: single scandir pass + chunked batch queries (chunk=500)
    - Phase 2: chunked NOT-IN queries for orphan galleries
    - Phase 3: single JOIN query for orphan blobs, batch update/delete
    """
    logger.info("[reconcile] Starting reconciliation")
    r = ctx["redis"]

    if not await _cron_should_run(ctx, "reconciliation", "0 3 * * 1"):
        logger.info("[reconcile] Skipping — cron gate not reached")
        return {"status": "skipped", "reason": "interval_not_reached"}

    await _cron_record(ctx, "reconciliation", "running")

    stats = {"removed_images": 0, "removed_galleries": 0, "orphan_blobs_cleaned": 0}

    lib_base = Path(settings.data_library_path)
    if not lib_base.exists():
        logger.info("[reconcile] library path does not exist, nothing to do")
        await _cron_record(ctx, "reconciliation", "ok")
        return {"status": "done", **stats}

    # ── Phase 1: Scan filesystem once, batch-query DB, reconcile in chunks ──

    # Two-level scandir pass: library structure is lib_base/source/source_id/.
    # gallery_map[(source, source_id)] = set of filenames on disk.
    # Broken symlinks are unlinked here; they are excluded from disk_files so
    # the subsequent DB diff will mark those image records for deletion.
    gallery_map: dict[tuple[str, str], set[str]] = {}
    empty_gallery_dirs: set[tuple[str, str]] = set()

    logger.info("[reconcile] Phase 1: scanning %s", lib_base)
    for source_entry in os.scandir(str(lib_base)):
        if not source_entry.is_dir(follow_symlinks=False):
            continue
        source = source_entry.name
        for sid_entry in os.scandir(source_entry.path):
            if not sid_entry.is_dir(follow_symlinks=False):
                continue
            source_id = sid_entry.name

            disk_files: set[str] = set()
            has_valid = False
            for fe in os.scandir(sid_entry.path):
                if fe.is_symlink() and not Path(fe.path).exists():
                    # Broken symlink — remove it silently; absence from disk_files
                    # will cause DB record to be deleted in batch step below.
                    try:
                        os.unlink(fe.path)
                    except OSError:
                        pass
                else:
                    disk_files.add(fe.name)
                    has_valid = True

            gallery_map[(source, source_id)] = disk_files
            if not has_valid:
                empty_gallery_dirs.add((source, source_id))

    all_fs_keys = sorted(gallery_map.keys())
    total_fs = len(all_fs_keys)
    logger.info("[reconcile] Phase 1: %d gallery dirs on disk", total_fs)

    _CHUNK = 500

    async with AsyncSessionLocal() as session:
        processed_p1 = 0
        for chunk_start in range(0, total_fs, _CHUNK):
            chunk_keys = all_fs_keys[chunk_start : chunk_start + _CHUNK]

            # Query Gallery records for this chunk using tuple IN
            galleries = (await session.execute(
                select(Gallery).where(
                    tuple_(Gallery.source, Gallery.source_id).in_(chunk_keys)
                )
            )).scalars().all()

            gallery_by_key = {(g.source, g.source_id): g for g in galleries}
            chunk_gallery_ids = [g.id for g in galleries]

            # Batch query images for galleries in this chunk
            rows = (await session.execute(
                select(Image.id, Image.gallery_id, Image.filename, Image.blob_sha256)
                .where(Image.gallery_id.in_(chunk_gallery_ids))
            )).all()

            # Build reverse map: gallery_id -> (source, source_id)
            id_to_key = {g.id: (g.source, g.source_id) for g in galleries}

            # Group DB rows by (source, source_id)
            db_by_gallery: dict[tuple[str, str], dict[str, tuple[int, str]]] = {}
            for row in rows:
                key = id_to_key.get(row.gallery_id)
                if key:
                    db_by_gallery.setdefault(key, {})[row.filename] = (row.id, row.blob_sha256)

            # Determine which image IDs and blob shas to remove for this chunk
            dead_image_ids: list[int] = []
            dead_blob_shas: list[str] = []

            for key in chunk_keys:
                disk_files = gallery_map[key]
                db_files = db_by_gallery.get(key, {})
                for filename, (img_id, sha) in db_files.items():
                    if filename not in disk_files:
                        dead_image_ids.append(img_id)
                        dead_blob_shas.append(sha)

            if dead_image_ids:
                # Batch decrement ref_counts
                await session.execute(
                    text(
                        "UPDATE blobs SET ref_count = ref_count - 1 "
                        "WHERE sha256 = ANY(:shas)"
                    ),
                    {"shas": dead_blob_shas},
                )
                # Batch delete images
                await session.execute(
                    text("DELETE FROM images WHERE id = ANY(:ids)"),
                    {"ids": dead_image_ids},
                )
                stats["removed_images"] += len(dead_image_ids)

            # Delete empty gallery dirs and their DB records in this chunk
            empty_in_chunk = [key for key in chunk_keys if key in empty_gallery_dirs]
            if empty_in_chunk:
                empty_gids = [gallery_by_key[k].id for k in empty_in_chunk if k in gallery_by_key]
                if empty_gids:
                    await session.execute(
                        text("DELETE FROM galleries WHERE id = ANY(:ids)"),
                        {"ids": empty_gids},
                    )
                    stats["removed_galleries"] += len(empty_gids)
                for key in empty_in_chunk:
                    source, sid = key
                    gdir = lib_base / source / sid
                    try:
                        gdir.rmdir()
                        # Also remove source dir if now empty
                        source_dir = lib_base / source
                        if source_dir.exists() and not any(source_dir.iterdir()):
                            source_dir.rmdir()
                    except OSError:
                        pass

            await session.commit()
            processed_p1 += len(chunk_keys)
            await r.setex(
                "reconcile:progress",
                3600,
                json.dumps({"phase": 1, "processed": processed_p1, "total": total_fs}),
            )

        logger.info("[reconcile] Phase 1 done: removed %d images, %d galleries",
                    stats["removed_images"], stats["removed_galleries"])

        # ── Phase 2: Orphan galleries — in DB but missing from filesystem ──
        # Query gallery rows and filter those whose (source, source_id) key is
        # not present on disk.

        logger.info("[reconcile] Phase 2: checking for orphan DB galleries")

        fs_keys = set(gallery_map.keys())

        db_gallery_rows = (await session.execute(
            select(Gallery.id, Gallery.source, Gallery.source_id)
            .where(Gallery.download_status != "proxy_only")
        )).all()

        orphan_gallery_ids = [
            row.id for row in db_gallery_rows
            if (row.source, row.source_id) not in fs_keys
        ]
        total_orphans = len(orphan_gallery_ids)
        logger.info("[reconcile] Phase 2: %d orphan galleries found", total_orphans)

        processed_p2 = 0
        for chunk_start in range(0, total_orphans, _CHUNK):
            chunk_ids = orphan_gallery_ids[chunk_start : chunk_start + _CHUNK]

            # Batch-fetch blob shas for images in these galleries
            orphan_rows = (await session.execute(
                select(Image.id, Image.blob_sha256)
                .where(Image.gallery_id.in_(chunk_ids))
            )).all()

            if orphan_rows:
                orphan_img_ids = [r.id for r in orphan_rows]
                orphan_shas = [r.blob_sha256 for r in orphan_rows]
                await session.execute(
                    text(
                        "UPDATE blobs SET ref_count = ref_count - 1 "
                        "WHERE sha256 = ANY(:shas)"
                    ),
                    {"shas": orphan_shas},
                )
                await session.execute(
                    text("DELETE FROM images WHERE id = ANY(:ids)"),
                    {"ids": orphan_img_ids},
                )
                stats["removed_images"] += len(orphan_img_ids)

            await session.execute(
                text("DELETE FROM galleries WHERE id = ANY(:ids)"),
                {"ids": chunk_ids},
            )
            stats["removed_galleries"] += len(chunk_ids)

            await session.commit()
            processed_p2 += len(chunk_ids)
            await r.setex(
                "reconcile:progress",
                3600,
                json.dumps({"phase": 2, "processed": processed_p2, "total": total_orphans}),
            )

        logger.info("[reconcile] Phase 2 done: removed %d orphan galleries", stats["removed_galleries"])

    # ── Phase 3: Blob GC — single batch query with actual ref counts ──

    logger.info("[reconcile] Phase 3: blob GC")

    _BLOB_CHUNK = 1000

    async with AsyncSessionLocal() as session:
        # Single query: join blobs with actual image ref count
        # Fetches only blobs where ref_count <= 0, with real count for safety
        gc_rows = (await session.execute(
            text("""
                SELECT b.sha256, b.extension, b.storage, b.external_path,
                       COUNT(i.id) AS actual_refs
                FROM blobs b
                LEFT JOIN images i ON i.blob_sha256 = b.sha256
                WHERE b.ref_count <= 0
                GROUP BY b.sha256, b.extension, b.storage, b.external_path
            """)
        )).all()

        total_gc = len(gc_rows)
        logger.info("[reconcile] Phase 3: %d candidate blobs to GC", total_gc)

        # Separate into: truly orphaned vs ref_count-drifted
        truly_orphaned = [r for r in gc_rows if r.actual_refs == 0]
        drifted = [r for r in gc_rows if r.actual_refs > 0]

        # Fix drifted ref_counts in batch (chunk to avoid huge IN lists)
        for chunk_start in range(0, len(drifted), _BLOB_CHUNK):
            chunk = drifted[chunk_start : chunk_start + _BLOB_CHUNK]
            for row in chunk:
                logger.warning(
                    "[reconcile] ref_count drift for %s: corrected to %d",
                    row.sha256[:12], row.actual_refs,
                )
                await session.execute(
                    text("UPDATE blobs SET ref_count = :rc WHERE sha256 = :sha"),
                    {"rc": row.actual_refs, "sha": row.sha256},
                )
            await session.commit()

        # Delete truly orphaned blobs in chunks
        processed_p3 = 0
        for chunk_start in range(0, len(truly_orphaned), _BLOB_CHUNK):
            chunk = truly_orphaned[chunk_start : chunk_start + _BLOB_CHUNK]
            chunk_shas = [r.sha256 for r in chunk]

            # Delete CAS files and thumb dirs first (filesystem ops)
            for row in chunk:
                cas_file = cas_path(row.sha256, row.extension)
                if cas_file.exists():
                    try:
                        cas_file.unlink()
                    except OSError as exc:
                        logger.warning("[reconcile] failed to delete CAS file %s: %s", cas_file, exc)

                td = thumb_dir(row.sha256)
                if td.exists():
                    shutil.rmtree(str(td), ignore_errors=True)

            # Batch delete blob records
            await session.execute(
                text("DELETE FROM blobs WHERE sha256 = ANY(:shas)"),
                {"shas": chunk_shas},
            )
            await session.commit()

            stats["orphan_blobs_cleaned"] += len(chunk)
            processed_p3 += len(chunk)
            await r.setex(
                "reconcile:progress",
                3600,
                json.dumps({"phase": 3, "processed": processed_p3, "total": total_gc}),
            )

        logger.info("[reconcile] Phase 3 done: cleaned %d orphan blobs (%d ref_count corrections)",
                    stats["orphan_blobs_cleaned"], len(drifted))

    await _cron_record(ctx, "reconciliation", "ok")

    # Store result in Redis for API query (30-day TTL)
    await r.setex("reconcile:last_result", 86400 * 30, json.dumps({
        "completed_at": datetime.now(UTC).isoformat(),
        **stats,
    }))

    logger.info("[reconcile] done: %s", stats)

    try:
        from core.events import EventType, emit
        await emit(EventType.RECONCILIATION_COMPLETED, resource_type="system", **stats)
    except Exception:
        pass

    return {"status": "done", **stats}
