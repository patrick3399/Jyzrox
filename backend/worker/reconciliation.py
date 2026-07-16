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
from services.cas import OWNER_MARKER_FILENAME, cas_path, create_library_symlink, safe_source_id, thumb_dir
from services.library_sidecar import SIDECAR_FILENAME, sidecar_payload_from_gallery, write_gallery_sidecar
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run

_CAS_ORPHAN_MIN_AGE_SECONDS = 24 * 3600  # files younger than this may belong to an in-flight import


async def _galleries_by_fs_key(session, chunk_keys: list[tuple[str, str]]) -> dict[tuple[str, str], Gallery]:
    """Map on-disk (source, dir_name) keys to their Gallery rows.

    Library directory names are produced by ``safe_source_id()``, so a raw
    ``tuple_(source, source_id).in_(...)`` misses galleries whose id was
    transformed ('/' → '__', edge case #46 residue): their symlink repair and
    image-level reconciliation were silently skipped. Fast path: raw tuple IN
    (covers ids that needed no sanitising). Keys still unmatched fall back to
    loading the affected sources and matching on the sanitized form.

    ``safe_source_id`` is lossy (#45): on a sanitized-name collision the first
    match keeps the directory and the other gallery is left untouched — the
    safe direction (skipped repair, never a wrongful delete).
    """
    rows = (
        (await session.execute(select(Gallery).where(tuple_(Gallery.source, Gallery.source_id).in_(chunk_keys))))
        .scalars()
        .all()
    )

    by_key: dict[tuple[str, str], Gallery] = {}
    for g in rows:
        by_key.setdefault((g.source, safe_source_id(g.source_id)), g)

    unmatched = [k for k in chunk_keys if k not in by_key]
    if unmatched:
        wanted_by_source: dict[str, set[str]] = {}
        for src, sid in unmatched:
            wanted_by_source.setdefault(src, set()).add(sid)
        for src, wanted in wanted_by_source.items():
            src_rows = (await session.execute(select(Gallery).where(Gallery.source == src))).scalars().all()
            for g in src_rows:
                sanitized = safe_source_id(g.source_id)
                if sanitized in wanted:
                    by_key.setdefault((src, sanitized), g)
    return by_key


def _orphan_gallery_ids(db_rows, fs_keys: set[tuple[str, str]]) -> list[int]:
    """Return ids of link-mode galleries whose library directory is missing on disk.

    On-disk directory names are produced by ``safe_source_id()`` (e.g. '/' -> '__'),
    so the DB ``source_id`` MUST be sanitized the same way before comparing against
    ``fs_keys``. Comparing the raw ``source_id`` wrongly flags link galleries whose
    id contains '/' (e.g. local imports 'artist/month/title') as filesystem orphans
    and deletes them (edge case #46). ``safe_source_id`` is lossy, so any collision
    only ever produces a false negative (a gallery is preserved), never a wrongful
    delete — the safe direction.
    """
    return [
        row.id
        for row in db_rows
        if (row.source, safe_source_id(row.source_id)) not in fs_keys
        and row.import_mode == "link"
        and row.deleted_at is None
    ]


async def reconciliation_job(ctx: dict, force: bool = False) -> dict:
    """
    Reconcile /data/library/ symlink tree with database records.

    Users can delete symlinks directly from filesystem. This job syncs
    those changes back to the database.

    Also runs blob GC: removes unreferenced blobs and their CAS files.

    Batch-optimised for 10M images / 100K galleries:
    - Phase 1: single scandir pass + chunked batch queries (chunk=500)
    - Phase 2: chunked NOT-IN queries for orphan galleries
    - Phase 3: single JOIN query for orphan blobs, batch update/delete
    - Phase 4: CAS scan for stale files with no blobs row (edge case #42)
    """
    logger.info("[reconcile] Starting reconciliation")
    r = ctx["redis"]

    if not force and not await _cron_should_run(ctx, "reconciliation", "0 3 * * 1"):
        logger.info("[reconcile] Skipping — cron gate not reached")
        return {"status": "skipped", "reason": "interval_not_reached"}

    await _cron_record(ctx, "reconciliation", "running")

    stats = {
        "removed_images": 0,
        "removed_galleries": 0,
        "orphan_blobs_cleaned": 0,
        "repaired_links": 0,
        "repaired_galleries": 0,
        "sidecars_written": 0,
        "cas_orphans_removed": 0,
    }

    lib_base = Path(settings.data_library_path)
    if not lib_base.exists():
        reason = "library_root_missing"
        logger.error("[reconcile] Aborting because library root is missing: %s", lib_base)
        await _cron_record(ctx, "reconciliation", "aborted", reason)
        return {"status": "aborted", "reason": reason, **stats}

    # ── Phase 1: Scan filesystem once, batch-query DB, reconcile in chunks ──

    # Two-level scandir pass: library structure is lib_base/source/source_id/.
    # gallery_map[(source, source_id)] = set of filenames on disk.
    # Broken symlinks are unlinked here; they are excluded from disk_files so
    # the subsequent DB diff will mark those image records for deletion.
    gallery_map: dict[tuple[str, str], set[str]] = {}
    empty_gallery_dirs: set[tuple[str, str]] = set()
    sidecar_missing: set[tuple[str, str]] = set()

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
            has_sidecar = False
            for fe in os.scandir(sid_entry.path):
                if fe.name == SIDECAR_FILENAME:
                    # Metadata sidecar, not gallery content: it must not make
                    # an empty dir look valid nor enter the DB/disk diff.
                    has_sidecar = True
                    continue
                if fe.name == OWNER_MARKER_FILENAME:
                    # Ownership marker (audit #45), not gallery content: same
                    # rules as the sidecar — never valid content, never diffed.
                    continue
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
            if not has_sidecar:
                sidecar_missing.add((source, source_id))

    all_fs_keys = sorted(gallery_map.keys())
    total_fs = len(all_fs_keys)
    logger.info("[reconcile] Phase 1: %d gallery dirs on disk", total_fs)

    _CHUNK = 500

    async with AsyncSessionLocal() as session:
        processed_p1 = 0
        for chunk_start in range(0, total_fs, _CHUNK):
            chunk_keys = all_fs_keys[chunk_start : chunk_start + _CHUNK]

            # Query Gallery records for this chunk. Directory names are
            # sanitized (safe_source_id), so matching must be too (#46 residue).
            gallery_by_key = await _galleries_by_fs_key(session, chunk_keys)
            chunk_gallery_ids = [g.id for g in gallery_by_key.values()]

            # Batch query images for galleries in this chunk
            rows = (
                await session.execute(
                    select(Image.id, Image.gallery_id, Image.filename, Image.blob_sha256, Blob)
                    .join(Blob, Blob.sha256 == Image.blob_sha256)
                    .where(Image.gallery_id.in_(chunk_gallery_ids))
                )
            ).all()

            # Build reverse map: gallery_id -> on-disk (source, dir_name) key
            id_to_key = {g.id: key for key, g in gallery_by_key.items()}

            # Group DB rows by (source, source_id)
            db_by_gallery: dict[tuple[str, str], dict[str, tuple[int, str, Blob]]] = {}
            for row in rows:
                key = id_to_key.get(row.gallery_id)
                if key:
                    db_by_gallery.setdefault(key, {})[row.filename] = (row.id, row.blob_sha256, row.Blob)

            # Determine which image IDs and blob shas to remove for this chunk
            dead_image_ids: list[int] = []
            dead_blob_shas: list[str] = []

            for key in chunk_keys:
                disk_files = gallery_map[key]
                gallery = gallery_by_key.get(key)
                db_files = db_by_gallery.get(key, {})
                for filename, (img_id, sha, blob) in db_files.items():
                    if filename not in disk_files:
                        if gallery and gallery.import_mode == "link":
                            dead_image_ids.append(img_id)
                            dead_blob_shas.append(sha)
                        elif gallery and filename:
                            try:
                                await create_library_symlink(gallery.source, gallery.source_id, filename, blob)
                                stats["repaired_links"] += 1
                            except Exception as exc:
                                logger.warning(
                                    "[reconcile] failed to repair library link for gallery=%d file=%s: %s",
                                    gallery.id,
                                    filename,
                                    exc,
                                )

            # Backfill the disaster-recovery sidecar (info.json) for matched,
            # non-trashed, non-empty gallery dirs that lack one — this is how
            # galleries imported before the sidecar existed get theirs.
            for key in chunk_keys:
                if key not in sidecar_missing or key in empty_gallery_dirs:
                    continue
                gallery = gallery_by_key.get(key)
                if gallery is None or gallery.deleted_at is not None:
                    continue
                if await write_gallery_sidecar(
                    gallery.source, gallery.source_id, sidecar_payload_from_gallery(gallery)
                ):
                    stats["sidecars_written"] += 1

            if dead_image_ids:
                # Batch decrement ref_counts
                await session.execute(
                    text("UPDATE blobs SET ref_count = ref_count - 1 WHERE sha256 = ANY(:shas)"),
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
                empty_gids = [
                    gallery_by_key[k].id
                    for k in empty_in_chunk
                    if k in gallery_by_key and gallery_by_key[k].import_mode == "link"
                ]
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
                        # The ownership marker (audit #45) must not keep an
                        # otherwise-empty gallery dir alive.
                        (gdir / OWNER_MARKER_FILENAME).unlink(missing_ok=True)
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

        logger.info(
            "[reconcile] Phase 1 done: removed %d images, %d galleries",
            stats["removed_images"],
            stats["removed_galleries"],
        )

        # ── Phase 2: Orphan galleries — in DB but missing from filesystem ──
        # Query gallery rows and filter those whose (source, source_id) key is
        # not present on disk.

        logger.info("[reconcile] Phase 2: checking for orphan DB galleries")

        fs_keys = set(gallery_map.keys())

        db_gallery_rows = (
            await session.execute(
                select(Gallery.id, Gallery.source, Gallery.source_id, Gallery.import_mode, Gallery.deleted_at).where(
                    Gallery.download_status != "proxy_only"
                )
            )
        ).all()

        orphan_gallery_ids = _orphan_gallery_ids(db_gallery_rows, fs_keys)
        total_orphans = len(orphan_gallery_ids)
        logger.info("[reconcile] Phase 2: %d orphan galleries found", total_orphans)

        if total_fs == 0 and db_gallery_rows:
            reason = "library_root_empty_with_db_galleries"
            logger.error(
                "[reconcile] Aborting destructive phases: library root is empty but DB contains %d galleries",
                len(db_gallery_rows),
            )
            await _cron_record(ctx, "reconciliation", "aborted", reason)
            return {"status": "aborted", "reason": reason, **stats}

        processed_p2 = 0
        for chunk_start in range(0, total_orphans, _CHUNK):
            chunk_ids = orphan_gallery_ids[chunk_start : chunk_start + _CHUNK]

            orphan_galleries = (await session.execute(select(Gallery).where(Gallery.id.in_(chunk_ids)))).scalars().all()
            orphan_rows = (
                await session.execute(
                    select(Image.gallery_id, Image.filename, Blob)
                    .join(Blob, Blob.sha256 == Image.blob_sha256)
                    .where(Image.gallery_id.in_(chunk_ids))
                )
            ).all()
            rows_by_gallery: dict[int, list] = {}
            for row in orphan_rows:
                rows_by_gallery.setdefault(row.gallery_id, []).append(row)

            # Missing library directories are repairable derived state. Rebuild
            # them from DB/blob metadata instead of deleting the source of truth.
            for gallery in orphan_galleries:
                for row in rows_by_gallery.get(gallery.id, []):
                    if not row.filename:
                        continue
                    try:
                        await create_library_symlink(gallery.source, gallery.source_id, row.filename, row.Blob)
                        stats["repaired_links"] += 1
                    except Exception as exc:
                        logger.warning(
                            "[reconcile] failed to rebuild gallery=%d file=%s: %s",
                            gallery.id,
                            row.filename,
                            exc,
                        )
                if await write_gallery_sidecar(
                    gallery.source,
                    gallery.source_id,
                    sidecar_payload_from_gallery(gallery),
                ):
                    stats["sidecars_written"] += 1
                    stats["repaired_galleries"] += 1

            processed_p2 += len(chunk_ids)
            await r.setex(
                "reconcile:progress",
                3600,
                json.dumps({"phase": 2, "processed": processed_p2, "total": total_orphans}),
            )

        logger.info("[reconcile] Phase 2 done: repaired %d orphan galleries", stats["repaired_galleries"])

    # ── Phase 3: Blob GC — single batch query with actual ref counts ──

    logger.info("[reconcile] Phase 3: blob GC")

    _BLOB_CHUNK = 1000

    async with AsyncSessionLocal() as session:
        # Single query: join blobs with actual image ref count.
        # Scan ALL blobs (not just ref_count <= 0) so that inflated ref_counts
        # caused by the former store_blob() bug are also detected and corrected.
        gc_rows = (
            await session.execute(
                text("""
                SELECT b.sha256, b.extension, b.storage, b.external_path,
                       b.ref_count,
                       COUNT(i.id) AS actual_refs
                FROM blobs b
                LEFT JOIN images i ON i.blob_sha256 = b.sha256
                GROUP BY b.sha256, b.extension, b.storage, b.external_path, b.ref_count
                HAVING b.ref_count != COUNT(i.id)
            """)
            )
        ).all()

        total_gc = len(gc_rows)
        logger.info("[reconcile] Phase 3: %d candidate blobs to GC", total_gc)

        # Separate into: truly orphaned (no Image rows) vs ref_count-drifted
        # (actual_refs > 0 but ref_count doesn't match, including inflated counts).
        truly_orphaned = [r for r in gc_rows if r.actual_refs == 0]
        drifted = [r for r in gc_rows if r.actual_refs > 0]

        # Fix drifted ref_counts in batch (chunk to avoid huge IN lists)
        for chunk_start in range(0, len(drifted), _BLOB_CHUNK):
            chunk = drifted[chunk_start : chunk_start + _BLOB_CHUNK]
            for row in chunk:
                logger.warning(
                    "[reconcile] ref_count drift for %s: corrected to %d",
                    row.sha256[:12],
                    row.actual_refs,
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

        logger.info(
            "[reconcile] Phase 3 done: cleaned %d orphan blobs (%d ref_count corrections)",
            stats["orphan_blobs_cleaned"],
            len(drifted),
        )

    # ── Phase 4: CAS orphan files — on disk but no blobs row (edge case #42) ──
    # store_blob() writes the CAS file before the DB transaction commits, so a
    # rollback (or crash mid-import) leaves files no blobs row references; blob
    # GC starts from DB rows and never sees them. Files younger than the age
    # threshold are skipped — they may belong to an import still in flight —
    # and a failed DB check aborts the phase (never delete blind).
    cas_base = Path(settings.data_cas_path)
    if cas_base.exists():
        cutoff = datetime.now(UTC).timestamp() - _CAS_ORPHAN_MIN_AGE_SECONDS
        candidates: list[tuple[str, Path]] = []
        for d1 in os.scandir(str(cas_base)):
            if not d1.is_dir(follow_symlinks=False):
                continue
            for d2 in os.scandir(d1.path):
                if not d2.is_dir(follow_symlinks=False):
                    continue
                for fe in os.scandir(d2.path):
                    if not fe.is_file(follow_symlinks=False):
                        continue
                    try:
                        if fe.stat().st_mtime > cutoff:
                            continue
                    except OSError:
                        continue
                    # Filenames are {sha256}{ext}; anything that does not parse
                    # to a known sha (e.g. stale .tmp files from crashed atomic
                    # promotes) simply never matches a blobs row.
                    candidates.append((fe.name.split(".", 1)[0], Path(fe.path)))

        orphan_paths: list[Path] = []
        if candidates:
            try:
                async with AsyncSessionLocal() as session:
                    for chunk_start in range(0, len(candidates), _BLOB_CHUNK):
                        chunk = candidates[chunk_start : chunk_start + _BLOB_CHUNK]
                        chunk_shas = [sha for sha, _ in chunk]
                        existing = set(
                            (await session.execute(select(Blob.sha256).where(Blob.sha256.in_(chunk_shas))))
                            .scalars()
                            .all()
                        )
                        orphan_paths.extend(path for sha, path in chunk if sha not in existing)
            except Exception as exc:
                logger.warning("[reconcile] Phase 4 aborted, keeping all CAS files (DB check failed): %s", exc)
                orphan_paths = []

        for path in orphan_paths:
            try:
                path.unlink()
                stats["cas_orphans_removed"] += 1
            except OSError as exc:
                logger.warning("[reconcile] failed to delete orphan CAS file %s: %s", path, exc)

        logger.info("[reconcile] Phase 4 done: removed %d row-less CAS files", stats["cas_orphans_removed"])

    await _cron_record(ctx, "reconciliation", "ok")

    # Store result in Redis for API query (30-day TTL)
    await r.setex(
        "reconcile:last_result",
        86400 * 30,
        json.dumps(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                **stats,
            }
        ),
    )

    logger.info("[reconcile] done: %s", stats)

    from core.events import EventType, emit_safe

    await emit_safe(EventType.RECONCILIATION_COMPLETED, resource_type="system", **stats)

    return {"status": "done", **stats}
