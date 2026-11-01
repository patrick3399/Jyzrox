"""Detached keep path for a stopped download that has no live execution.

``POST /api/download/jobs/{id}/stop`` hands a live job to its own worker, which
runs the keep path inside ``_run_download_job``. A job nobody is executing has no
such worker: it is still queued, it is paused after a worker restart, or its
worker died after the stop was recorded. This task finishes those jobs the same
way: end ``done`` with ``progress.outcome == "stopped"``, keep what was fetched,
and move the subscription boundary.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from core.config import settings
from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from core.redis_client import publish_job_event
from db.models import DownloadJob, Gallery
from services.download_mode import REPAIR, effective_mode
from services.download_stop import run_started_at
from worker.constants import logger
from worker.download import _import_staged_leftovers, _set_subscription_result
from worker.helpers import _set_job_progress

_ACTIVE_STATUSES = ("queued", "paused", "running")


def _collection_lock_key(row) -> str | None:
    """Redis lock key of a Pixiv author-collection job's run, or None for any other job."""
    if (row.options if isinstance(row.options, dict) else {}).get("pixiv_collection") is not True:
        return None
    if row.user_id is None:
        return None
    from plugins.builtin.pixiv.source import PixivSourcePlugin

    match = PixivSourcePlugin.user_match(row.url)
    if not match:
        return None
    return f"pixiv:collection:lock:{row.user_id}:{int(match.group(1))}"


async def _collection_is_live(ctx: dict, row) -> bool:
    """Whether a Pixiv author-collection job is still executing.

    That job never takes an admission token, so ``admission_token IS NULL`` does
    not prove it is dead. Its run holds a Redis lock whose value is the job id.
    """
    redis = ctx.get("redis")
    if redis is None:
        return False
    try:
        key = _collection_lock_key(row)
        if key is None:
            return False
        holder = await redis.get(key)
    except Exception as exc:
        logger.warning("[finalize_stopped] could not read the collection lock for %s: %s", row.id, exc)
        return False
    return holder in (str(row.id), str(row.id).encode())


async def release_dead_collection_lock(redis, job) -> None:
    """Drop the lock a dead author-collection run left behind (worker restart).

    Startup recovery calls this for a stop-requested job before handing it to
    ``finalize_stopped_job``, which would otherwise take the stale lock for a
    live run. Best effort.
    """
    try:
        key = _collection_lock_key(job)
        if key is not None and (await redis.get(key)) in (str(job.id), str(job.id).encode()):
            await redis.delete(key)
    except Exception as exc:
        logger.warning("[finalize_stopped] could not release the collection lock of %s: %s", job.id, exc)


async def _resolve_target(plugin_registry, url: str, db_job_id: str, options: dict | None) -> tuple:
    """The plugin that handles ``url`` and its staging dir, as the live run resolves them."""
    plugin = await plugin_registry.get_handler(url)
    if not plugin:
        plugin = plugin_registry.get_fallback()
    base = Path(settings.data_gallery_path)
    if (options or {}).get("pixiv_collection") is True:
        from plugins.builtin.pixiv.source import PixivSourcePlugin

        match = PixivSourcePlugin.user_match(url)
        if match:
            return plugin, base / "pixiv" / f"user_{match.group(1)}"
    downloader = plugin_registry.get_downloader(plugin.meta.source_id) if plugin else None
    if downloader:
        return plugin, downloader.resolve_output_dir(url, base, db_job_id)
    return plugin, base / db_job_id


async def finalize_stopped_job(ctx: dict, db_job_id: str) -> dict:
    """Finish a stop-requested job that no worker is executing.

    Ignored unless the job still exists, is queued/paused/running, carries a stop
    intent and has no admission token (a token means a live execution, which runs
    its own keep path). The job is marked ``done`` first, under a row lock, so a
    second delivery, a late ``download_job`` dispatch and a cancel all see a
    terminal job; the gallery work follows.
    """
    try:
        job_uuid = uuid.UUID(str(db_job_id))
    except ValueError:
        return {"status": "ignored"}

    # ── 1. Claim: lock the row and end it ───────────────────────────────
    # Column selects only: loading a DownloadJob entity first would let the lock
    # read stale status/admission_token from the identity map (claim invariant).
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(
                    DownloadJob.id,
                    DownloadJob.url,
                    DownloadJob.source,
                    DownloadJob.status,
                    DownloadJob.mode,
                    DownloadJob.options,
                    DownloadJob.user_id,
                    DownloadJob.gallery_id,
                    DownloadJob.progress,
                    DownloadJob.admission_token,
                    DownloadJob.stop_requested_at,
                )
                .where(DownloadJob.id == job_uuid)
                .with_for_update()
            )
        ).one_or_none()
        if row is None or row.stop_requested_at is None:
            return {"status": "ignored"}
        if row.status not in _ACTIVE_STATUSES or row.admission_token is not None:
            return {"status": "ignored"}
        # A collection job takes no admission token, so a live run (paused or not)
        # shows up here as token-less; its Redis lock says whether it is executing.
        if row.status in ("running", "paused") and await _collection_is_live(ctx, row):
            return {"status": "ignored"}

        progress = dict(row.progress or {})
        # The run's own start; a job that never ran has none and leaves the boundary alone.
        boundary = run_started_at(progress)
        done_progress = {**progress, "outcome": "stopped", "status_text": "Stopped", "gdl_state": "done"}
        await session.execute(
            update(DownloadJob)
            .where(DownloadJob.id == job_uuid)
            .values(status="done", finished_at=datetime.now(UTC), error=None, progress=done_progress)
        )
        await session.commit()

    with contextlib.suppress(Exception):
        await publish_job_event(
            {
                "type": "job_update",
                "job_id": db_job_id,
                "status": "done",
                "progress": done_progress,
                "user_id": row.user_id,
            }
        )
    redis = ctx.get("redis")
    if redis is not None:
        # The stop flag and a pause flag belong to a job that no longer exists.
        with contextlib.suppress(Exception):
            await redis.delete(f"download:cancel:{db_job_id}", f"download:pause:{db_job_id}")

    options = row.options if isinstance(row.options, dict) else {}
    mode = effective_mode(row.mode if isinstance(row.mode, str) else None, options)

    # ── 2. Subscription boundary ────────────────────────────────────────
    # boundary=None still records the stopped status but never moves the cutoff.
    # Before the gallery work: it is quick, and a timeout or cancellation inside
    # the keep below must not leave the boundary unmoved for good (the job is
    # already `done`, so nothing would ever run this again).
    await _set_subscription_result(db_job_id, "stopped", boundary=boundary)

    # ── 3. Keep what the interrupted run fetched, then refresh the library ─
    gallery_id = await _keep_gallery(db_job_id, row, options, mode, done_progress)
    if gallery_id:
        await emit_safe(EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=gallery_id)
    logger.info("[finalize_stopped] job %s finished as stopped (gallery_id=%s)", db_job_id, gallery_id)
    return {"status": "done", "outcome": "stopped", "gallery_id": gallery_id}


def _has_staged_files(target_dir: Path) -> bool:
    """Whether the staging dir exists and holds anything."""
    try:
        return target_dir.is_dir() and any(target_dir.iterdir())
    except OSError:
        return False


async def _keep_gallery(db_job_id: str, row, options: dict, mode: str, done_progress: dict) -> int | None:
    """Import staging leftovers and finalize the job's gallery; returns its id if one is kept.

    A job that never ran has no gallery and an absent or empty staging dir, so
    there is nothing to keep and no gallery to touch. That is judged from the
    data, not from ``status``: a job that ran can be ``queued`` again after a
    retry or a resume. Never raises: the job is already ``done``, so a failure
    here is logged and left for reconciliation.
    """
    from plugins.registry import plugin_registry
    from worker.progressive import ProgressiveImporter, _rmtree_staging_dir

    importer = ProgressiveImporter(
        db_job_id,
        row.user_id,
        include_excluded=bool(options.get("include_excluded")) and mode == REPAIR,
    )
    importer.source_url = row.url
    try:
        plugin, target_dir = await _resolve_target(plugin_registry, row.url, db_job_id, options)
        if not row.gallery_id and not await asyncio.to_thread(_has_staged_files, target_dir):
            return None
        is_gallery_dl = plugin is not None and plugin.meta.source_id == "gallery_dl"
        is_collection = options.get("pixiv_collection") is True

        attached = bool(row.gallery_id) and await importer.attach_existing_gallery(row.gallery_id)
        if is_gallery_dl:
            from plugins.builtin.gallery_dl._archive import repair_archive_tables
            from plugins.builtin.gallery_dl._identity import resolve_url_identity

            if mode == REPAIR:
                importer.repair_archive = repair_archive_tables(row.url, db_job_id)
            if not attached:
                # The archive table is named after the source, which a run that
                # never created a gallery has not set.
                identity = resolve_url_identity(row.url)
                if identity is not None:
                    importer.source = identity.source

        # BE-T17: a trashed gallery is never touched, so nothing to import or finalize.
        if not attached or importer.skipped_trashed:
            await importer.discard_unlinked_archive_entries()
            _rmtree_staging_dir(target_dir)
            return None

        if not is_collection:
            # A collection imports each file as it finishes, so its staging holds
            # nothing the run did not already hand over.
            await _import_staged_leftovers(importer, target_dir, importer.import_file)
        gallery_id = await importer.finalize_kept(target_dir, mode=mode)
        if gallery_id:
            await _record_kept(db_job_id, importer, gallery_id, done_progress)
        return gallery_id
    except Exception as exc:
        logger.error("[finalize_stopped] keep path failed for job %s: %s", db_job_id, exc, exc_info=True)
        await importer.abort()
        return None


async def _record_kept(db_job_id: str, importer, gallery_id: int, done_progress: dict) -> None:
    """Add the kept gallery and its page count to the job's progress."""
    async with AsyncSessionLocal() as session:
        pages = (await session.execute(select(Gallery.pages).where(Gallery.id == gallery_id))).scalar_one_or_none()
    progress = {**done_progress, "gallery_id": gallery_id, "status_text": f"Stopped — kept {pages or 0}"}
    if isinstance(importer.title, str) and importer.title:
        progress["title"] = importer.title
    failures = importer.import_failures
    if failures:
        progress["import_failures"] = {
            "count": len(failures),
            "success": importer.import_success_count,
            "details": list(failures[:10]),
        }
    await _set_job_progress(db_job_id, progress)
