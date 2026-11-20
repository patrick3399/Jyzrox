"""Library auto-discovery and scheduled scan jobs."""

import asyncio
from pathlib import Path

from sqlalchemy.sql import select

import core.queue
from core.database import AsyncSessionLocal
from core.local_patterns import build_library_pattern_regex, normalize_relative_path
from db.models import Gallery
from services.link_sync import sync_link_gallery
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run
from worker.scan_common import (
    _discover_single_library_dir,
    _existing_local_status,
    _get_library_specs,
    _ImportRequest,
    _media_count,
    _walk_library_tree,
    _watcher_work_enabled,
)
from worker.scan_rescan_library import rescan_library_job
from worker.scan_vanished import _reconnect_vanished_gallery, _vanished_link_source_paths


async def auto_discover_job(ctx: dict, watcher_origin: bool = False) -> dict:
    """Scan all library paths recursively and auto-create galleries for undiscovered directories containing media files."""
    if not await _watcher_work_enabled(ctx, watcher_origin):
        logger.info("[auto_discover] Skipping queued watcher job because monitoring is disabled")
        return {"status": "skipped", "reason": "watcher_disabled", "discovered": 0}
    logger.info("[auto_discover] Starting auto-discovery")

    discovered = 0
    skipped_existing = 0
    reconnected = 0
    vanished: list[str] | None = None
    import_requests: list[_ImportRequest] = []
    async with AsyncSessionLocal() as session:
        specs = await _get_library_specs(session, monitored_only=watcher_origin)

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
            for dirpath, filenames in await asyncio.to_thread(_walk_library_tree, str(lib_dir)):
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
                if existing is not None:
                    skipped_existing += 1
                    continue

                if vanished is None:
                    vanished = await _vanished_link_source_paths(session)
                outcome = await _reconnect_vanished_gallery(
                    ctx, session, current, vanished, watcher_origin=watcher_origin
                )
                if outcome is not None:
                    if outcome.get("status") == "moved":
                        reconnected += 1
                        vanished = None
                    continue

                import_request = await _discover_single_library_dir(session, spec, current)
                if import_request:
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

    logger.info(
        "[auto_discover] Discovered %d new galleries; reconnected %d; skipped %d existing galleries",
        discovered,
        reconnected,
        skipped_existing,
    )

    from core.events import EventType, emit_safe

    await emit_safe(EventType.GALLERY_DISCOVERED, resource_type="gallery", discovered=discovered)

    return {"discovered": discovered}


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
                    for dirpath, filenames in await asyncio.to_thread(_walk_library_tree, str(lib_dir)):
                        current = Path(dirpath)
                        if current == lib_dir or _media_count(filenames) == 0:
                            continue
                        try:
                            rel_path = normalize_relative_path(str(current.relative_to(lib_dir)))
                        except ValueError:
                            continue
                        if pattern_re.match(rel_path):
                            # Replaying local_import_job for a gallery that already
                            # finished importing re-hashes every file and makes new
                            # folders queue behind the whole library (2026-09-26: one
                            # new gallery waited 396 s behind 1,391 replays). Existing
                            # galleries are refreshed by rescan_gallery_job below; an
                            # interrupted import is still replayed (HR-019).
                            existing_status = await _existing_local_status(session, rel_path)
                            if existing_status is not None and existing_status != "importing":
                                continue
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


async def sync_all_link_galleries(ctx: dict) -> dict:
    """Fingerprint-check every link gallery.

    Opening a gallery only compares the directory mtime, which a file rewritten
    in place does not move. This sweep forces the full stat diff, and also picks
    up folders nobody has opened while the watcher was off.
    """
    async with AsyncSessionLocal() as session:
        gallery_ids = (
            (
                await session.execute(
                    select(Gallery.id)
                    .where(
                        Gallery.import_mode == "link",
                        Gallery.source_path.is_not(None),
                        Gallery.deleted_at.is_(None),
                    )
                    .order_by(Gallery.id)
                )
            )
            .scalars()
            .all()
        )

    changed = 0
    for gallery_id in gallery_ids:
        result = await sync_link_gallery(gallery_id, redis=ctx["redis"], force=True)
        if result.changed:
            changed += 1
    logger.info("[link_sweep] checked %d link galleries, %d changed", len(gallery_ids), changed)
    return {"checked": len(gallery_ids), "changed": changed}


async def scheduled_scan_job(ctx: dict, force: bool = False) -> dict:
    """Scheduled library scan — uses croniter-based gating."""
    if not force and not await _cron_should_run(ctx, "library_scan", "0 * * * *"):
        return {"status": "skipped"}

    try:
        await _cron_record(ctx, "library_scan", "running")
        logger.info("[scheduled_scan] Starting scheduled library scan")
        await auto_discover_job(ctx)
        await rescan_library_job(ctx)
        await sync_all_link_galleries(ctx)
        await _cron_record(ctx, "library_scan", "ok")
        logger.info("[scheduled_scan] Scheduled scan complete")
        return {"status": "done"}
    except Exception as exc:
        await _cron_record(ctx, "library_scan", "failed", str(exc))
        raise
