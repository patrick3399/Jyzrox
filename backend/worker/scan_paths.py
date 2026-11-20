"""Path-scoped reconcile and rescan jobs."""

import asyncio
import os
from pathlib import Path

from sqlalchemy.sql import select

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from db.models import Gallery, Image
from worker.constants import logger
from worker.helpers import _sha256
from worker.scan_common import (
    _discover_single_library_dir,
    _get_library_specs,
    _list_file_names,
    _media_count,
    _stat_and_list_media,
    _watcher_work_enabled,
)
from worker.scan_move import move_library_path_job
from worker.scan_rescan_gallery import rescan_gallery_job
from worker.scan_vanished import _reconnect_vanished_gallery, _vanished_link_source_paths


async def reconcile_library_path_job(
    ctx: dict,
    old_paths: list[str],
    new_path: str,
    destination_device: int | None = None,
    destination_inode: int | None = None,
    watcher_origin: bool = False,
) -> dict:
    """Pair unmatched cross-root create/delete events by exact gallery content."""
    from sqlalchemy.orm import selectinload

    if not await _watcher_work_enabled(ctx, watcher_origin):
        return {"status": "skipped", "reason": "watcher_disabled", "new_path": new_path}

    new_real = os.path.realpath(new_path)
    destination = Path(new_real)
    try:
        destination_stat, listed_media = await asyncio.to_thread(_stat_and_list_media, destination)
        media_files = sorted(listed_media)
    except OSError:
        return {"status": "stale", "reason": "destination_unavailable", "new_path": new_real}
    if destination_device is not None and destination_stat.st_dev != destination_device:
        return {"status": "stale", "reason": "destination_replaced", "new_path": new_real}
    if destination_inode is not None and destination_stat.st_ino != destination_inode:
        return {"status": "stale", "reason": "destination_replaced", "new_path": new_real}

    normalized_old_paths = sorted({os.path.realpath(path) for path in old_paths if path})
    async with AsyncSessionLocal() as session:
        candidates = (
            (
                await session.execute(
                    select(Gallery)
                    .where(Gallery.source == "local", Gallery.source_path.in_(normalized_old_paths))
                    .options(selectinload(Gallery.images).selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

    if not candidates:
        return await rescan_by_path_job(ctx, new_real, watcher_origin=watcher_origin)
    if not media_files:
        return {"status": "conflict", "reason": "candidate_gallery_but_no_media", "new_path": new_real}

    # The watcher pairs a create with every delete inside its window, so most
    # candidates here are unrelated. Names + sizes are enough to rule those out,
    # and cost one stat per file instead of hashing the whole directory: a bulk
    # reorganisation would otherwise sha256 every moved gallery once per
    # candidate directory. Only survivors get hashed, and the exact content
    # signature below still decides the match.
    try:
        destination_sizes = sorted((path.name, path.stat().st_size) for path in media_files)
    except OSError:
        return {"status": "stale", "reason": "destination_unavailable", "new_path": new_real}

    def _size_signature(gallery) -> list[tuple[str, int]]:
        signature: list[tuple[str, int]] = []
        for image in gallery.images:
            if not image.filename:
                continue
            if image.blob is not None:
                signature.append((image.filename, image.blob.file_size))
            elif image.external_path is not None and image.source_size is not None:
                # A pending link page has no blob yet; its registered size
                # stands in for it.
                signature.append((image.filename, image.source_size))
        return sorted(signature)

    plausible = [g for g in candidates if g.images and _size_signature(g) == destination_sizes]
    if not plausible:
        logger.info(
            "[reconcile_library_path] no candidate matches names/sizes for %s (%d considered); skipping hashing",
            new_real,
            len(candidates),
        )
        return {"status": "conflict", "reason": "content_mismatch", "new_path": new_real}

    # Pending pages have no hash, so they take no part in the hash signature on
    # either side: the destination files that correspond to a candidate's
    # pending pages are neither hashed nor compared. Hashes are computed once
    # per file name and only for names some candidate needs.
    destination_hashes: dict[str, str] = {}

    async def _destination_signature(gallery) -> list[tuple[str, str]]:
        pending_names = {image.filename for image in gallery.images if image.filename and image.blob_sha256 is None}
        signature = []
        for path in media_files:
            if path.name in pending_names:
                continue
            if path.name not in destination_hashes:
                destination_hashes[path.name] = await asyncio.to_thread(_sha256, path)
            signature.append((path.name, destination_hashes[path.name]))
        return sorted(signature)

    matches = []
    for gallery in plausible:
        gallery_signature = sorted(
            (image.filename, image.blob_sha256) for image in gallery.images if image.filename and image.blob_sha256
        )
        if gallery_signature == await _destination_signature(gallery):
            matches.append(gallery)
    if len(matches) != 1:
        reason = "content_mismatch" if not matches else "ambiguous_content_match"
        logger.warning(
            "[reconcile_library_path] %s for %s across %d candidate galleries",
            reason,
            new_real,
            len(candidates),
        )
        return {"status": "conflict", "reason": reason, "new_path": new_real}

    gallery = matches[0]
    if gallery.deleted_at is not None:
        return {"status": "skipped", "reason": "trashed", "gallery_id": gallery.id, "new_path": new_real}
    return await move_library_path_job(
        ctx,
        old_path=gallery.source_path or normalized_old_paths[0],
        new_path=new_real,
        destination_device=destination_device,
        destination_inode=destination_inode,
        watcher_origin=watcher_origin,
    )


async def rescan_by_path_job(ctx: dict, dir_path: str, watcher_origin: bool = False) -> dict:
    """Rescan the gallery whose files reside in dir_path."""
    if not await _watcher_work_enabled(ctx, watcher_origin):
        logger.info("[rescan_by_path] Skipping queued watcher job because monitoring is disabled")
        return {"status": "skipped", "reason": "watcher_disabled", "path": dir_path}
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
        specs = await _get_library_specs(session, monitored_only=watcher_origin)
        matching_specs = [
            spec
            for spec in specs
            if real_dir == os.path.realpath(spec.path) or real_dir.startswith(os.path.realpath(spec.path) + os.sep)
        ]
        matching_specs.sort(key=lambda spec: len(os.path.realpath(spec.path)), reverse=True)
        current = Path(real_dir)
        if current.is_dir():
            try:
                filenames = await asyncio.to_thread(_list_file_names, current)
            except OSError:
                filenames = []
            if _media_count(filenames) > 0:
                if matching_specs:
                    outcome = await _reconnect_vanished_gallery(
                        ctx,
                        session,
                        current,
                        await _vanished_link_source_paths(session),
                        watcher_origin=watcher_origin,
                    )
                    if outcome is not None:
                        return outcome
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
                .where(
                    Image.external_path.like(
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
    if watcher_origin:
        await core.queue.enqueue("auto_discover_job", watcher_origin=True)
    else:
        await core.queue.enqueue("auto_discover_job")
    return {"status": "no_gallery_found", "path": dir_path}
