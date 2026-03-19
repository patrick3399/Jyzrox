"""
ARQ Worker entry point.

Run with:  arq worker.WorkerSettings
"""

import asyncio
import json
import logging
import os

from core.compat import patch_asyncio_for_314

patch_asyncio_for_314()

from datetime import UTC

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func as arq_func

from core.config import get_all_library_paths, settings
from core.redis_client import close_redis, init_redis
from core.watcher import LibraryWatcher
from worker.dedup_scan import dedup_scan_job
from worker.dedup_tier1 import dedup_tier1_job
from worker.dedup_tier2 import dedup_tier2_job
from worker.dedup_tier3 import dedup_tier3_job
from worker.download import download_job as _download_job
from worker.ehtag_sync import ehtag_sync_job
from worker.gallery_dl_venv import ensure_venv
from worker.gallery_dl_venv import rollback_job as gdl_rollback_job
from worker.gallery_dl_venv import upgrade_job as gdl_upgrade_job
from worker.helpers import _sha256, compute_arq_job_id, enqueue_download_job
from worker.importer import (
    _build_gallery,
    _extract_tags,
    _normalize_tags,
    _upsert_tags,
    batch_import_job,
    import_job,
    local_import_job,
)
from worker.reconciliation import reconciliation_job
from worker.retry import retry_failed_downloads_job
from worker.scan import (
    auto_discover_job,
    rescan_by_path_job,
    rescan_gallery_job,
    rescan_library_job,
    rescan_library_path_job,
    scheduled_scan_job,
)
from worker.subscription import (
    check_followed_artists,
    check_single_subscription,
)
from worker.tagging import tag_job
from worker.thumbhash_backfill import thumbhash_backfill_job
from worker.thumbnail import thumbnail_job
from worker.trash import trash_gc_job

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


# ── Lifecycle ────────────────────────────────────────────────────────

_watcher = LibraryWatcher()


async def _log_level_subscriber(ctx: dict) -> None:
    """Subscribe to log_level:changed pub/sub and apply new level when source==worker."""
    from core.log_handler import LOG_LEVEL_CHANNEL
    from core.redis_client import get_pubsub

    pubsub = get_pubsub()
    try:
        await pubsub.subscribe(LOG_LEVEL_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    payload = json.loads(data)
                    if payload.get("source") == "worker":
                        level = payload.get("level", "INFO").upper()
                        logging.getLogger().setLevel(level)
                        logger.info("[log_level_subscriber] Level changed to %s", level)
                except Exception as exc:
                    logger.warning("[log_level_subscriber] Failed to process message: %s", exc)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("[log_level_subscriber] Subscriber exited with error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe(LOG_LEVEL_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass


async def startup(ctx: dict) -> None:
    logger.info("ARQ Worker started — Jyzrox")
    await init_redis()
    from core.log_handler import apply_log_level_from_redis, install_log_handler

    install_log_handler("worker")
    await apply_log_level_from_redis("worker")
    from plugins import init_plugins

    await init_plugins()
    from core.site_config import site_config_service

    await site_config_service.start_listener()
    logger.info("SiteConfigService listener started")
    from core.adaptive import adaptive_engine

    loaded = await adaptive_engine.load_all_from_db()
    if loaded:
        logger.info("Loaded %d adaptive states from DB", loaded)
    # Initialize gallery-dl venv (before recovery — downloads need it)
    try:
        await ensure_venv()
    except Exception as exc:
        logger.error("gallery-dl venv initialization failed: %s", exc)
    # Start log level subscriber background task
    ctx["_log_level_task"] = asyncio.ensure_future(_log_level_subscriber(ctx))
    r = ctx["redis"]
    # Clean up ALL download semaphore keys (including dynamic gallery_dl:{domain} ones)
    sem_keys = [k async for k in r.scan_iter(match="download:sem:*")]
    if sem_keys:
        await r.delete(*sem_keys)
    # Clean up stale scan progress from previous runs
    await r.delete(
        "rescan:progress",
        "rescan:cancel",
        "dedup:progress:status",
        "dedup:progress:signal",
        "dedup:progress:current",
        "dedup:progress:total",
        "dedup:progress:tier",
        "dedup:progress:mode",
    )

    # Clean orphaned cancel/PID Redis keys (stale from previous session)
    cancel_keys = [k async for k in r.scan_iter(match="download:cancel:*")]
    if cancel_keys:
        await r.delete(*cancel_keys)
    pid_keys = [k async for k in r.scan_iter(match="download:pid:*")]
    if pid_keys:
        await r.delete(*pid_keys)
    # NOTE: do NOT delete download:pause:* — paused jobs are preserved

    from datetime import UTC, datetime

    from sqlalchemy import func, select, update

    from core.database import AsyncSessionLocal
    from db.models import DownloadJob, Gallery

    async with AsyncSessionLocal() as session:
        # Recovery: running → queued (re-enqueue, not fail)
        running_jobs = (
            (await session.execute(select(DownloadJob).where(DownloadJob.status == "running"))).scalars().all()
        )
        if running_jobs:
            arq_pool = ctx["redis"]

            # Fix orphaned galleries stuck in "downloading" status (batch query)
            from db.models import Image

            gallery_ids = [job.gallery_id for job in running_jobs if job.gallery_id is not None]
            if gallery_ids:
                counts = {
                    row[0]: row[1]
                    for row in (
                        await session.execute(
                            select(Image.gallery_id, func.count())
                            .where(Image.gallery_id.in_(gallery_ids))
                            .group_by(Image.gallery_id)
                        )
                    ).all()
                }
                for gid in gallery_ids:
                    await session.execute(
                        update(Gallery)
                        .where(Gallery.id == gid, Gallery.download_status == "downloading")
                        .values(download_status="partial", pages=counts.get(gid, 0))
                    )
                await session.commit()
                logger.info("Fixed %d orphaned downloading galleries", len(gallery_ids))

            # Re-enqueue recovered jobs (set status + enqueue atomically per job)
            for job in running_jobs:
                job.retry_count = (job.retry_count or 0) + 1
                arq_job_id = compute_arq_job_id(job.id, job.retry_count)
                try:
                    await enqueue_download_job(arq_pool, job, arq_job_id)
                    job.status = "queued"
                    job.error = None
                    job.finished_at = None
                    logger.info("Re-enqueued recovered running job %s (retry=%d)", job.id, job.retry_count)
                except Exception as exc:
                    job.status = "failed"
                    job.error = f"Re-enqueue failed on startup: {exc}"
                    job.finished_at = datetime.now(UTC)
                    logger.error("Failed to re-enqueue job %s: %s", job.id, exc)
            await session.commit()
            logger.info("Recovered %d stale running jobs from previous worker session", len(running_jobs))

        # Re-enqueue stale "queued" jobs that survived a crash
        stale_queued = (
            (await session.execute(select(DownloadJob).where(DownloadJob.status == "queued"))).scalars().all()
        )
        if stale_queued:
            arq_pool = ctx["redis"]
            for job in stale_queued:
                arq_job_id = compute_arq_job_id(job.id, job.retry_count)
                try:
                    await enqueue_download_job(arq_pool, job, arq_job_id)
                    logger.info("Re-enqueued stale queued job %s", job.id)
                except Exception as exc:
                    job.status = "failed"
                    job.error = f"Re-enqueue failed on startup: {exc}"
                    job.finished_at = datetime.now(UTC)
                    logger.error("Failed to re-enqueue job %s: %s", job.id, exc)
            await session.commit()
            logger.info("Processed %d stale queued jobs", len(stale_queued))

        # Paused jobs: re-enqueue so ARQ result is written (pause gate catches them)
        # This ensures the resume endpoint can detect "coroutine dead" and re-enqueue properly.
        # Without this, resume after restart thinks the coroutine is alive and sets status
        # to "running" without re-enqueueing — leaving the job stuck forever.
        paused_jobs = (await session.execute(select(DownloadJob).where(DownloadJob.status == "paused"))).scalars().all()
        if paused_jobs:
            arq_pool = ctx["redis"]
            for job in paused_jobs:
                arq_job_id = compute_arq_job_id(job.id, job.retry_count)
                try:
                    await enqueue_download_job(arq_pool, job, arq_job_id)
                    logger.info("Re-enqueued paused job %s (pause gate will catch it)", job.id)
                except Exception as exc:
                    logger.error("Failed to re-enqueue paused job %s: %s", job.id, exc)
            logger.info("Re-enqueued %d paused jobs from previous session", len(paused_jobs))

    # Clean up orphaned per-job config files
    import glob as _glob

    orphan_configs = _glob.glob("/app/config/gallery-dl-*.json")
    if orphan_configs:
        for cfg_path in orphan_configs:
            try:
                os.remove(cfg_path)
            except OSError:
                pass
        logger.info("Cleaned up %d orphaned gallery-dl config files", len(orphan_configs))

    # Start file system watcher.
    # Honour the runtime override stored by toggle_monitor; fall back to the
    # static config flag when no override has been set yet.
    watcher_enabled_raw = await r.get("watcher:enabled")
    if watcher_enabled_raw is None:
        # No override stored — initialise from config and persist it.
        watcher_should_start = settings.library_monitor_enabled
        await r.set("watcher:enabled", "1" if watcher_should_start else "0")
    else:
        watcher_should_start = watcher_enabled_raw not in (b"0", "0")

    if watcher_should_start:
        paths = await get_all_library_paths()
        loop = asyncio.get_event_loop()
        arq_pool = ctx["redis"]

        def enqueue_sync(job_name: str, *args):
            asyncio.run_coroutine_threadsafe(arq_pool.enqueue_job(job_name, *args), loop)

        _watcher.start(paths, enqueue_sync)
        await r.set(
            "watcher:status",
            json.dumps({"running": True, "paths": paths}),
        )


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ Worker shutting down")
    _watcher.stop()
    # Cancel log level subscriber
    log_level_task = ctx.get("_log_level_task")
    if log_level_task is not None and not log_level_task.done():
        log_level_task.cancel()
        try:
            await log_level_task
        except asyncio.CancelledError:
            pass
    r = ctx["redis"]
    await r.delete("watcher:status")
    await close_redis()


# ── Toggle Watcher ────────────────────────────────────────────────────


async def toggle_watcher_job(ctx: dict, enabled: bool) -> dict:
    """Start or stop the file system watcher on behalf of the API.

    The API cannot directly touch the watchdog Observer because it lives in the
    worker process.  Instead the API enqueues this job so the worker acts on the
    desired state immediately.

    The ``watcher:enabled`` Redis key (already written by the API before
    enqueuing this job) serves as the durable record that ``startup()`` reads on
    the next worker restart.
    """
    r = ctx["redis"]
    if enabled:
        if _watcher.is_running:
            logger.info("[toggle_watcher] Already running — no-op")
            return {"status": "already_running"}

        paths = await get_all_library_paths()
        if not paths:
            logger.warning("[toggle_watcher] No library paths configured — cannot start watcher")
            await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
            return {"status": "no_paths"}

        loop = asyncio.get_event_loop()
        arq_pool = ctx["redis"]

        def enqueue_sync(job_name: str, *args):
            asyncio.run_coroutine_threadsafe(arq_pool.enqueue_job(job_name, *args), loop)

        _watcher.start(paths, enqueue_sync)
        await r.set("watcher:status", json.dumps({"running": True, "paths": paths}))
        logger.info("[toggle_watcher] Started, watching %d path(s)", len(paths))
        return {"status": "started", "paths": paths}
    else:
        if not _watcher.is_running:
            logger.info("[toggle_watcher] Already stopped — no-op")
            await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
            return {"status": "already_stopped"}

        _watcher.stop()
        await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
        logger.info("[toggle_watcher] Stopped")
        return {"status": "stopped"}


# ── Rate Limit Schedule ───────────────────────────────────────────────


async def rate_limit_schedule_job(ctx: dict) -> dict:
    """Check the rate limit schedule and update the active flag in Redis."""
    from datetime import datetime, timezone  # noqa: F401

    r = ctx["redis"]

    enabled_val = await r.get("rate_limit:schedule:enabled")
    enabled = enabled_val in (b"1", "1")

    if not enabled:
        await r.delete("rate_limit:schedule:active")
        return {"status": "disabled"}

    start_val = await r.get("rate_limit:schedule:start_hour")
    end_val = await r.get("rate_limit:schedule:end_hour")

    try:
        start_hour = int(start_val) if start_val is not None else 0
    except (ValueError, TypeError):
        start_hour = 0

    try:
        end_hour = int(end_val) if end_val is not None else 6
    except (ValueError, TypeError):
        end_hour = 6

    current_hour = datetime.now(UTC).hour

    if start_hour <= end_hour:
        in_window = start_hour <= current_hour < end_hour
    else:
        # Wraps midnight: e.g. 22–06
        in_window = current_hour >= start_hour or current_hour < end_hour

    if in_window:
        await r.set("rate_limit:schedule:active", "1")
        return {"status": "active", "hour": current_hour}
    else:
        await r.delete("rate_limit:schedule:active")
        return {"status": "inactive", "hour": current_hour}


# ── Log Cleanup ───────────────────────────────────────────────────────


async def log_cleanup_job(ctx: dict) -> dict:
    """Trim system_logs list: remove entries older than retention_days and cap at max_entries."""
    from datetime import UTC, datetime, timedelta

    from core.redis_client import get_redis

    r = get_redis()

    # Read settings
    max_entries_val = await r.get("setting:log_max_entries")
    retention_days_val = await r.get("setting:log_retention_days")

    try:
        max_entries = int(max_entries_val) if max_entries_val is not None else 10000
    except (ValueError, TypeError):
        max_entries = 10000

    try:
        retention_days = int(retention_days_val) if retention_days_val is not None else 7
    except (ValueError, TypeError):
        retention_days = 7

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    raw_list = await r.lrange("system_logs", 0, -1)
    kept = []
    removed = 0
    for raw in raw_list:
        try:
            entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            ts_str = entry.get("timestamp", "")
            ts = datetime.fromisoformat(ts_str)
            if ts >= cutoff:
                kept.append(raw)
            else:
                removed += 1
        except Exception:
            kept.append(raw)

    # Rebuild list if any entries were removed
    if removed > 0:
        pipe = r.pipeline(transaction=False)
        pipe.delete("system_logs")
        for item in kept:
            pipe.rpush("system_logs", item)
        await pipe.execute()

    # Cap to max_entries
    await r.ltrim("system_logs", 0, max_entries - 1)

    logger.info("[log_cleanup_job] Removed %d stale entries, capped to %d", removed, max_entries)
    return {"removed": removed, "max_entries": max_entries}


async def disk_monitor_job(ctx: dict) -> dict:
    """Cron: check disk space, set/clear Redis flag, emit event when low."""
    from core.config import settings
    from worker.constants import DISK_LOW_KEY
    from worker.helpers import check_disk_space

    disk_ok, free_gb = check_disk_space("/data", settings.disk_min_free_gb)
    r = ctx["redis"]

    if not disk_ok:
        await r.set(DISK_LOW_KEY, str(free_gb), ex=600)
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.SYSTEM_DISK_LOW,
            resource_type="system",
            free_gb=free_gb,
            threshold_gb=settings.disk_min_free_gb,
        )
        logger.warning("[disk_monitor] LOW: %.2f GB free (min %.1f GB)", free_gb, settings.disk_min_free_gb)
        return {"status": "low", "free_gb": free_gb}

    await r.delete(DISK_LOW_KEY)
    return {"status": "ok", "free_gb": free_gb}


async def adaptive_persist_job(ctx: dict) -> dict:
    """Persist dirty adaptive states from Redis to database."""
    from core.adaptive import adaptive_engine

    count = await adaptive_engine.persist_dirty()
    return {"persisted": count}


# ── ARQ Worker Settings ──────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        arq_func(_download_job, name="download_job", max_tries=1),
        import_job,
        local_import_job,
        batch_import_job,
        rescan_library_job,
        rescan_gallery_job,
        rescan_by_path_job,
        rescan_library_path_job,
        auto_discover_job,
        tag_job,
        thumbnail_job,
        reconciliation_job,
        scheduled_scan_job,
        toggle_watcher_job,
        check_followed_artists,
        check_single_subscription,
        dedup_tier1_job,
        dedup_tier2_job,
        dedup_tier3_job,
        dedup_scan_job,
        rate_limit_schedule_job,
        thumbhash_backfill_job,
        retry_failed_downloads_job,
        trash_gc_job,
        ehtag_sync_job,
        log_cleanup_job,
        arq_func(gdl_upgrade_job, name="gdl_upgrade_job", max_tries=1),
        arq_func(gdl_rollback_job, name="gdl_rollback_job", max_tries=1),
        disk_monitor_job,
        adaptive_persist_job,
    ]
    cron_jobs = [
        cron(
            scheduled_scan_job,
            hour=None,  # every hour
            minute=0,  # at :00
            run_at_startup=False,
            unique=True,
            timeout=7200,
        ),
        cron(
            reconciliation_job,
            weekday=0,  # Monday
            hour=3,
            minute=0,
            unique=True,
            timeout=3600,
        ),
        cron(
            check_followed_artists,
            hour={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22},
            minute=30,
            run_at_startup=False,
            unique=True,
            timeout=3600,
        ),
        cron(
            rate_limit_schedule_job,
            minute={0, 10, 20, 30, 40, 50},
            run_at_startup=False,
            unique=True,
            timeout=60,
        ),
        cron(
            retry_failed_downloads_job,
            minute={0, 15, 30, 45},
            run_at_startup=False,
            unique=True,
            timeout=300,
        ),
        cron(
            trash_gc_job,
            hour=4,
            minute=0,
            unique=True,
            timeout=3600,
        ),
        cron(
            ehtag_sync_job,
            hour=4,
            minute=30,
            run_at_startup=True,  # ensures first-boot import
            unique=True,
            timeout=300,
        ),
        cron(
            log_cleanup_job,
            hour=3,
            minute=30,
            unique=True,
            timeout=300,
        ),
        cron(
            disk_monitor_job,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
            unique=True,
            timeout=30,
        ),
        cron(
            adaptive_persist_job,
            minute=set(range(0, 60, 5)),
            run_at_startup=False,
            unique=True,
            timeout=60,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = int(os.environ.get("MAX_WORKER_JOBS", "8"))
    job_timeout = 3600
    poll_delay = 2


__all__ = [
    "_download_job",
    "import_job",
    "local_import_job",
    "batch_import_job",
    "rescan_library_job",
    "rescan_gallery_job",
    "rescan_by_path_job",
    "rescan_library_path_job",
    "auto_discover_job",
    "scheduled_scan_job",
    "thumbnail_job",
    "reconciliation_job",
    "tag_job",
    "check_followed_artists",
    "check_single_subscription",
    "dedup_tier1_job",
    "dedup_tier2_job",
    "dedup_tier3_job",
    "dedup_scan_job",
    "toggle_watcher_job",
    "rate_limit_schedule_job",
    "thumbhash_backfill_job",
    "retry_failed_downloads_job",
    "trash_gc_job",
    "ehtag_sync_job",
    "log_cleanup_job",
    "gdl_upgrade_job",
    "gdl_rollback_job",
    "disk_monitor_job",
    "adaptive_persist_job",
    "startup",
    "shutdown",
    "WorkerSettings",
    # Internal helpers re-exported for tests
    "_extract_tags",
    "_normalize_tags",
    "_build_gallery",
    "_upsert_tags",
    "_sha256",
    "compute_arq_job_id",
    "enqueue_download_job",
]
