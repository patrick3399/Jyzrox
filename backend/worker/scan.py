"""Library scan and rescan jobs for the worker package."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text, update
from sqlalchemy.sql import select

import core.queue
from core.config import get_all_library_paths, settings
from core.database import AsyncSessionLocal
from core.local_patterns import (
    DEFAULT_IMPORT_MODE,
    DEFAULT_LIBRARY_PATTERN,
    build_library_pattern_regex,
    normalize_relative_path,
)
from core.source_display import get_display_config
from db.models import Blob, ExcludedBlob, Gallery, Image, LibraryPath
from services.cas import (
    create_library_symlink,
    decrement_ref_count,
    library_dir,
    resolve_blob_path,
    store_blob,
    thumb_dir,
)
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run, _sha256

_SUPPORTED_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}


@dataclass(frozen=True)
class _LibrarySpec:
    path: str
    pattern: str = DEFAULT_LIBRARY_PATTERN
    import_mode: str = DEFAULT_IMPORT_MODE


@dataclass(frozen=True)
class _ImportRequest:
    gallery_id: int
    source_dir: str
    mode: str


def _cover_image_for_gallery(
    gallery: Gallery, images: list[Image], excluded_set: set[str] | None = None
) -> Image | None:
    excluded = excluded_set or set()
    eligible = []
    for img in images:
        visibility = getattr(img, "visibility", "active")
        if not isinstance(visibility, str):
            visibility = "active"
        if visibility != "active":
            continue
        if getattr(img, "blob_sha256", None) in excluded:
            continue
        eligible.append(img)
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda img: img.page_num)
    cfg = get_display_config(gallery.source or "")
    return ordered[-1] if cfg.cover_page == "last" else ordered[0]


def _has_thumb_160(blob: Blob) -> bool:
    return (thumb_dir(blob.sha256) / "thumb_160.webp").exists()


async def _get_library_specs(session) -> list[_LibrarySpec]:
    rows = (
        (
            await session.execute(
                select(LibraryPath).where(LibraryPath.enabled == True)  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    specs = [
        _LibrarySpec(
            path=row.path,
            pattern=row.pattern or DEFAULT_LIBRARY_PATTERN,
            import_mode=row.import_mode or DEFAULT_IMPORT_MODE,
        )
        for row in rows
    ]
    seen = {spec.path for spec in specs}

    for path in await get_all_library_paths():
        if path not in seen:
            specs.append(_LibrarySpec(path=path))
            seen.add(path)
    return specs


def _media_count(filenames: list[str]) -> int:
    return sum(1 for f in filenames if Path(f).suffix.lower() in _SUPPORTED_MEDIA_EXTS)


def _match_library_candidate(spec: _LibrarySpec, root: Path, candidate: Path) -> tuple[str, dict[str, str]] | None:
    try:
        rel_path = normalize_relative_path(str(candidate.relative_to(root)))
    except ValueError:
        return None
    match = build_library_pattern_regex(spec.pattern).match(rel_path)
    if not match:
        return None
    return rel_path, match.groupdict()


async def _discover_single_library_dir(session, spec: _LibrarySpec, current: Path) -> _ImportRequest | None:
    root = Path(spec.path)
    matched = _match_library_candidate(spec, root, current)
    if not matched:
        return None
    rel_path, groups = matched
    title = groups.get("title") or current.name
    artist = groups.get("artist")
    source_path = os.path.realpath(current)

    stmt = text(
        "INSERT INTO galleries "
        "(source, source_id, title, artist_id, uploader, library_path, source_path, import_mode, download_status) "
        "VALUES ('local', :source_id, :title, :artist_id, :uploader, :library_path, :source_path, :import_mode, 'importing') "
        "ON CONFLICT (source, source_id) DO UPDATE SET "
        "title = EXCLUDED.title, "
        "artist_id = EXCLUDED.artist_id, "
        "uploader = EXCLUDED.uploader, "
        "library_path = EXCLUDED.library_path, "
        "source_path = EXCLUDED.source_path, "
        "import_mode = EXCLUDED.import_mode "
        "RETURNING id"
    )
    result = await session.execute(
        stmt,
        {
            "source_id": rel_path,
            "title": title,
            "artist_id": f"local:{artist}" if artist else None,
            "uploader": artist,
            "library_path": spec.path,
            "source_path": source_path,
            "import_mode": spec.import_mode,
        },
    )
    gallery_id = result.scalar_one_or_none()
    if gallery_id is None:
        return None
    return _ImportRequest(gallery_id=gallery_id, source_dir=source_path, mode=spec.import_mode)


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

                for gid in chunk_ids:
                    gallery = gallery_map.get(gid)
                    if not gallery:
                        continue

                    images = images_by_gallery.get(gid, [])
                    missing_thumb = False
                    missing_cover_thumb = False
                    removed = 0
                    cover_image = _cover_image_for_gallery(gallery, images)
                    existing_images_for_cover: list[Image] = []

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
                        existing_images_for_cover.append(img)
                        has_thumb = _has_thumb_160(blob)
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
                        if current_cover and current_cover.blob and not _has_thumb_160(current_cover.blob):
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
                    unique_shas = list(sha_counts.keys())
                    decrements = [sha_counts[s] for s in unique_shas]
                    await session.execute(
                        text("""
                            UPDATE blobs SET ref_count = ref_count - v.n
                            FROM (SELECT unnest(:shas ::text[]) AS sha,
                                         unnest(:ns ::int[])  AS n) v
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
        excluded_rows = (
            (await session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
            .scalars()
            .all()
        )
        excluded_set: set[str] = set(excluded_rows)

        import shutil

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

        # --- Step 1: Verify existing records ---
        known_sha256s: set[str] = set()
        missing_thumb = False
        missing_cover_thumb = False
        removed = 0
        cover_image = _cover_image_for_gallery(gallery, images, excluded_set)
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
            has_thumb = _has_thumb_160(blob)
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
                dir_files = sorted(
                    [f for f in gallery_dir.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_MEDIA_EXTS],
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
                        gallery_id,
                        file_hash[:12],
                        fpath.name,
                    )
                    continue
                # New file found on disk that is not in the DB.
                if gallery.import_mode == "link":
                    blob = await store_blob(fpath, file_hash, session, storage="external", external_path=str(fpath))
                else:
                    blob = await store_blob(fpath, file_hash, session)
                await create_library_symlink(gallery.source, gallery.source_id, fpath.name, blob)
                await session.flush()
                max_page += 1
                stmt = (
                    pg_insert_local(Image)
                    .values(
                        gallery_id=gallery_id,
                        page_num=max_page,
                        filename=fpath.name,
                        blob_sha256=file_hash,
                    )
                    .on_conflict_do_nothing()
                    .returning(Image.id)
                )
                result = await session.execute(stmt)
                inserted = result.scalar_one_or_none()

                if inserted is not None:
                    # New Image row created — increment blob ref_count.
                    await session.execute(
                        update(Blob).where(Blob.sha256 == file_hash).values(ref_count=Blob.ref_count + 1)
                    )
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
        gallery.last_scanned_at = datetime.now(UTC)

        await session.commit()

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


async def auto_discover_job(ctx: dict) -> dict:
    """Scan all library paths recursively and auto-create galleries for undiscovered directories containing media files."""
    logger.info("[auto_discover] Starting auto-discovery")

    discovered = 0
    import_requests: list[_ImportRequest] = []
    async with AsyncSessionLocal() as session:
        specs = await _get_library_specs(session)

        for spec in specs:
            lib_dir = Path(spec.path)
            if not lib_dir.is_dir():
                continue
            try:
                pattern_re = build_library_pattern_regex(spec.pattern)
            except ValueError as exc:
                logger.warning("[auto_discover] skipping invalid pattern for %s: %s", spec.path, exc)
                continue

            # Walk the directory tree recursively; os.walk is efficient for deep trees
            for dirpath, dirnames, filenames in os.walk(str(lib_dir)):
                # Skip hidden directories in-place so os.walk won't descend into them
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

                current = Path(dirpath)
                # Skip the library root itself — only subfolders are gallery candidates
                if current == lib_dir:
                    continue

                try:
                    rel_path = normalize_relative_path(str(current.relative_to(lib_dir)))
                except ValueError:
                    continue

                match = pattern_re.match(rel_path)
                if not match:
                    continue

                # Only create a gallery if the directory directly contains media files
                file_count = _media_count(filenames)
                if file_count == 0:
                    continue

                existing = (
                    await session.execute(
                        select(Gallery.id).where(Gallery.source == "local", Gallery.source_id == rel_path)
                    )
                ).scalar_one_or_none()

                import_request = await _discover_single_library_dir(session, spec, current)
                if import_request:
                    if existing is None:
                        discovered += 1
                    import_requests.append(import_request)
                    logger.info("[auto_discover] Gallery matched: %s (%d files)", rel_path, file_count)

        await session.commit()

    for item in import_requests:
        await core.queue.enqueue(
            "local_import_job",
            source_dir=item.source_dir,
            mode=item.mode,
            gallery_id=item.gallery_id,
            _timeout=3600,
            _job_id=f"local-import:{item.gallery_id}",
        )

    logger.info("[auto_discover] Discovered %d new galleries", discovered)

    from core.events import EventType, emit_safe

    await emit_safe(EventType.GALLERY_DISCOVERED, resource_type="gallery", discovered=discovered)

    return {"discovered": discovered}


async def rescan_by_path_job(ctx: dict, dir_path: str) -> dict:
    """Rescan the gallery whose files reside in dir_path."""
    # In CAS mode, /data/library/{gallery_id}/ is the gallery directory.
    lib_base = Path(settings.data_library_path)
    dir_p = Path(dir_path)
    real_dir = os.path.realpath(dir_path)

    gallery_id: int | None = None
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Gallery.id).where(Gallery.source_path == real_dir).limit(1))
        gallery_id = result.scalar_one_or_none()

    if gallery_id:
        return await rescan_gallery_job(ctx, gallery_id)

    async with AsyncSessionLocal() as session:
        specs = await _get_library_specs(session)
        matching_specs = [
            spec
            for spec in specs
            if real_dir == os.path.realpath(spec.path) or real_dir.startswith(os.path.realpath(spec.path) + os.sep)
        ]
        matching_specs.sort(key=lambda spec: len(os.path.realpath(spec.path)), reverse=True)
        current = Path(real_dir)
        if current.is_dir():
            try:
                filenames = [p.name for p in current.iterdir() if p.is_file()]
            except OSError:
                filenames = []
            if _media_count(filenames) > 0:
                for spec in matching_specs:
                    import_request = await _discover_single_library_dir(session, spec, current)
                    if import_request:
                        await session.commit()
                        await core.queue.enqueue(
                            "local_import_job",
                            source_dir=import_request.source_dir,
                            mode=import_request.mode,
                            gallery_id=import_request.gallery_id,
                            _timeout=3600,
                            _job_id=f"local-import:{import_request.gallery_id}",
                        )
                        return {"status": "discovered", "path": real_dir, "gallery_id": import_request.gallery_id}

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
    except ValueError, IndexError:
        pass

    if not gallery_id:
        # Try checking if it's a blob external path
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Image.gallery_id)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .where(
                    Blob.external_path.like(
                        dir_path.replace("%", "\\%").replace("_", "\\_") + "%",
                        escape="\\",
                    )
                )
                .limit(1)
            )
            gallery_id = result.scalar_one_or_none()

    if gallery_id:
        return await rescan_gallery_job(ctx, gallery_id)

    # No existing gallery found — might be a new directory, trigger auto-discover
    await core.queue.enqueue("auto_discover_job")
    return {"status": "no_gallery_found", "path": dir_path}


async def rescan_library_path_job(ctx: dict, library_path: str) -> dict:
    """Rescan all galleries that belong to a specific library path."""
    import json as _json

    logger.info("[rescan_path] starting rescan for path: %s", library_path)
    r = ctx["redis"]
    import_requests: list[_ImportRequest] = []

    async with AsyncSessionLocal() as session:
        specs = await _get_library_specs(session)
        spec = next((item for item in specs if item.path == library_path), None)
        if spec:
            lib_dir = Path(spec.path)
            if lib_dir.is_dir():
                try:
                    pattern_re = build_library_pattern_regex(spec.pattern)
                except ValueError as exc:
                    logger.warning("[rescan_path] skipping discovery for invalid pattern %s: %s", spec.path, exc)
                else:
                    for dirpath, dirnames, filenames in os.walk(str(lib_dir)):
                        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                        current = Path(dirpath)
                        if current == lib_dir or _media_count(filenames) == 0:
                            continue
                        try:
                            rel_path = normalize_relative_path(str(current.relative_to(lib_dir)))
                        except ValueError:
                            continue
                        if pattern_re.match(rel_path):
                            import_request = await _discover_single_library_dir(session, spec, current)
                            if import_request:
                                import_requests.append(import_request)
                    await session.commit()

        relevant = (
            (await session.execute(select(Gallery).where(Gallery.library_path == library_path).order_by(Gallery.id)))
            .scalars()
            .all()
        )

        total = len(relevant)
        logger.info("[rescan_path] %d galleries under %s", total, library_path)

    for item in import_requests:
        await core.queue.enqueue(
            "local_import_job",
            source_dir=item.source_dir,
            mode=item.mode,
            gallery_id=item.gallery_id,
            _timeout=3600,
            _job_id=f"local-import:{item.gallery_id}",
        )

    importing_gallery_ids = {item.gallery_id for item in import_requests}
    # Enqueue each gallery rescan as a child job so a large library path does
    # not exceed the parent job's timeout.
    for idx, gallery in enumerate(relevant):
        if gallery.id in importing_gallery_ids:
            continue
        await r.setex(
            "rescan:progress",
            3600,
            _json.dumps(
                {
                    "processed": idx,
                    "total": total,
                    "status": "running",
                    "current_gallery": gallery.id,
                }
            ),
        )
        await core.queue.enqueue("rescan_gallery_job", gallery_id=gallery.id, _timeout=3600)

    await r.setex(
        "rescan:progress",
        30,
        _json.dumps(
            {
                "processed": total,
                "total": total,
                "status": "done",
            }
        ),
    )
    logger.info("[rescan_path] completed, %d galleries processed", total)
    return {"status": "done", "total": total}


async def scheduled_scan_job(ctx: dict, force: bool = False) -> dict:
    """Scheduled library scan — uses croniter-based gating."""
    if not force and not await _cron_should_run(ctx, "library_scan", "0 * * * *"):
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
