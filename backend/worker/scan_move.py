"""Monitored library path move job."""

import asyncio
import os
from pathlib import Path

from sqlalchemy.sql import select

import core.queue
from core.database import AsyncSessionLocal
from db.models import BlobLocation, Gallery, Image
from worker.constants import logger
from worker.helpers import _sha256
from worker.scan_common import (
    _discover_single_library_dir,
    _get_library_specs,
    _LibrarySpec,
    _list_file_names,
    _match_library_candidate,
    _media_count,
    _watcher_work_enabled,
)
from worker.scan_move_prep import _LibraryMoveConflict, _LibraryMoveFilesystemState, _prepare_library_move
from worker.scan_vanished import _reconnect_vanished_gallery, _vanished_link_source_paths


async def move_library_path_job(
    ctx: dict,
    old_path: str,
    new_path: str,
    destination_device: int | None = None,
    destination_inode: int | None = None,
    watcher_origin: bool = False,
) -> dict:
    """Apply one monitored directory move without replacing gallery identity."""
    from sqlalchemy.orm import selectinload

    if not await _watcher_work_enabled(ctx, watcher_origin):
        logger.info("[move_library_path] Skipping queued watcher job because monitoring is disabled")
        return {"status": "skipped", "reason": "watcher_disabled", "old_path": old_path, "new_path": new_path}

    old_real = os.path.realpath(old_path)
    new_real = os.path.realpath(new_path)
    destination = Path(new_real)
    try:
        destination_stat = destination.stat()
    except OSError:
        return {"status": "stale", "reason": "destination_unavailable", "new_path": new_real}
    if not destination.is_dir():
        return {"status": "ignored", "reason": "destination_not_directory", "new_path": new_real}
    if destination_device is not None and destination_stat.st_dev != destination_device:
        return {"status": "stale", "reason": "destination_replaced", "new_path": new_real}
    if destination_inode is not None and destination_stat.st_ino != destination_inode:
        return {"status": "stale", "reason": "destination_replaced", "new_path": new_real}

    filesystem_state: _LibraryMoveFilesystemState | None = None
    gallery_id: int | None = None
    old_source_id: str | None = None
    new_source_id: str | None = None
    try:
        async with AsyncSessionLocal() as session:
            specs = await _get_library_specs(session, monitored_only=watcher_origin)
            matches: list[tuple[int, _LibrarySpec, str]] = []
            for spec in specs:
                root = Path(os.path.realpath(spec.path))
                try:
                    matched = _match_library_candidate(spec, root, destination)
                except ValueError as exc:
                    logger.warning("[move_library_path] skipping invalid pattern for %s: %s", spec.path, exc)
                    continue
                if matched:
                    matches.append((len(str(root)), spec, matched[0]))
            if not matches:
                return {"status": "ignored", "reason": "destination_not_monitored", "new_path": new_real}
            matches.sort(key=lambda item: item[0], reverse=True)
            _, destination_spec, new_source_id = matches[0]

            galleries = (
                (
                    await session.execute(
                        select(Gallery)
                        .where(Gallery.source == "local", Gallery.source_path == old_real)
                        .options(selectinload(Gallery.images).selectinload(Image.blob))
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            if len(galleries) > 1:
                raise _LibraryMoveConflict(f"multiple galleries claim source path {old_real}")
            if not galleries:
                descendant = (
                    await session.execute(
                        select(Gallery.id)
                        .where(Gallery.source == "local")
                        .where(Gallery.source_path.startswith(old_real.rstrip(os.sep) + os.sep, autoescape=True))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if descendant is not None:
                    return {
                        "status": "ignored",
                        "reason": "parent_move_has_gallery_descendants",
                        "old_path": old_real,
                        "new_path": new_real,
                    }

                filenames = await asyncio.to_thread(_list_file_names, destination)
                if _media_count(filenames) == 0:
                    return {"status": "ignored", "reason": "no_media", "new_path": new_real}
                # The old path may be a stop along the way: an earlier rename of
                # this folder could have gone unseen.
                outcome = await _reconnect_vanished_gallery(
                    ctx,
                    session,
                    destination,
                    await _vanished_link_source_paths(session),
                    watcher_origin=watcher_origin,
                )
                if outcome is not None:
                    return outcome
                import_request = await _discover_single_library_dir(session, destination_spec, destination)
                if import_request is None:
                    await session.rollback()
                    return {"status": "ignored", "reason": "discovery_conflict", "new_path": new_real}
                await session.commit()
                await core.queue.enqueue(
                    "local_import_job",
                    source_dir=import_request.source_dir,
                    mode=import_request.mode,
                    gallery_id=import_request.gallery_id,
                    _timeout=3600,
                    _job_id=f"local-import:{import_request.gallery_id}",
                )
                return {"status": "discovered", "gallery_id": import_request.gallery_id, "new_path": new_real}

            gallery = galleries[0]
            gallery_id = gallery.id
            old_source_id = gallery.source_id
            if gallery.deleted_at is not None:
                return {"status": "skipped", "reason": "trashed", "gallery_id": gallery.id}

            collision = (
                await session.execute(
                    select(Gallery.id)
                    .where(
                        Gallery.source == "local",
                        Gallery.source_id == new_source_id,
                        Gallery.id != gallery.id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if collision is not None:
                raise _LibraryMoveConflict(
                    f"destination source identity local:{new_source_id} already belongs to gallery {collision}"
                )

            new_external_paths: dict[int, str] = {}
            for image in gallery.images:
                if not image.filename or Path(image.filename).name != image.filename:
                    raise _LibraryMoveConflict(f"image {image.id} has an unsafe filename: {image.filename!r}")
                moved_image_path = destination / image.filename
                if not moved_image_path.is_file():
                    raise _LibraryMoveConflict(
                        f"moved image path is unavailable for image {image.id}: {moved_image_path}"
                    )
                is_pending = image.blob_sha256 is None
                if is_pending:
                    # A pending link page has no hash to compare. Its size, taken
                    # when it was registered, is the strongest check available
                    # without hashing the whole folder on the move path.
                    if image.external_path is None or image.source_size is None:
                        raise _LibraryMoveConflict(f"image {image.id} has no blob and no recorded size to verify")
                    if moved_image_path.stat().st_size != image.source_size:
                        raise _LibraryMoveConflict(
                            f"moved image size does not match pending image {image.id}: {moved_image_path}"
                        )
                else:
                    moved_hash = await asyncio.to_thread(_sha256, moved_image_path)
                    if moved_hash != image.blob_sha256:
                        raise _LibraryMoveConflict(
                            f"moved image content does not match image {image.id}: {moved_image_path}"
                        )

                if gallery.import_mode == "link":
                    if image.external_path is None:
                        raise _LibraryMoveConflict(f"link gallery image {image.id} has no external path")
                    try:
                        relative = Path(image.external_path).relative_to(old_real)
                    except ValueError as exc:
                        raise _LibraryMoveConflict(
                            f"image {image.id} path {image.external_path} is outside moved directory {old_real}"
                        ) from exc
                    moved_external_path = str(destination / relative)
                    if Path(moved_external_path) != moved_image_path:
                        raise _LibraryMoveConflict(
                            f"image {image.id} filename and external path disagree after move: {moved_external_path}"
                        )
                    new_external_paths[image.id] = moved_external_path
                    if moved_external_path != image.external_path and not is_pending:
                        location = await session.get(BlobLocation, (image.blob_sha256, moved_external_path))
                        if location is None:
                            session.add(BlobLocation(blob_sha256=image.blob_sha256, external_path=moved_external_path))

            await session.flush()
            filesystem_state = await _prepare_library_move(
                gallery,
                new_source_id,
                list(gallery.images),
                new_external_paths,
            )
            for image in gallery.images:
                if image.id in new_external_paths:
                    image.external_path = new_external_paths[image.id]
            gallery.source_id = new_source_id
            gallery.source_path = new_real
            gallery.library_path = destination_spec.path
            if gallery.download_status == "missing":
                gallery.download_status = "complete"
            await session.commit()
    except _LibraryMoveConflict as exc:
        logger.warning("[move_library_path] refusing %s -> %s: %s", old_real, new_real, exc)
        return {"status": "conflict", "error": str(exc), "old_path": old_real, "new_path": new_real}
    except Exception:
        if filesystem_state is not None:
            try:
                filesystem_state.rollback()
            except Exception:
                logger.exception("[move_library_path] Failed to roll back library filesystem state")
        raise

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.GALLERY_UPDATED,
        resource_type="gallery",
        resource_id=gallery_id,
        reason="monitored_source_moved",
        old_source_id=old_source_id,
        source_id=new_source_id,
        old_path=old_real,
        source_path=new_real,
    )
    return {
        "status": "moved",
        "gallery_id": gallery_id,
        "old_source_id": old_source_id,
        "source_id": new_source_id,
        "old_path": old_real,
        "new_path": new_real,
    }
