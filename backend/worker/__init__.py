"""
SAQ Worker entry point.

Run with:  python -m worker
"""

import asyncio
import json
import logging
import os
from datetime import UTC

from saq import CronJob

from core.config import get_all_library_paths, settings
from core.redis_client import close_redis
from core.scheduled_task_catalog import CATALOG
from core.watcher import LibraryWatcher
from worker.backup import database_backup_job
from worker.dedup_scan import dedup_scan_job
from worker.dedup_tier1 import dedup_tier1_job
from worker.dedup_tier2 import dedup_tier2_job
from worker.dedup_tier3 import dedup_tier3_job
from worker.download import download_job
from worker.ehtag_sync import ehtag_sync_job
from worker.gallery_dl_venv import ensure_venv
from worker.gallery_dl_venv import rollback_job as gdl_rollback_job
from worker.gallery_dl_venv import upgrade_job as gdl_upgrade_job
from worker.helpers import _sha256, compute_job_key, enqueue_download_job, env_int
from worker.importer import (
    _build_gallery,
    _extract_tags,
    _normalize_tags,
    _upsert_tags,
    batch_import_job,
    import_job,
    local_import_job,
)
from worker.memory import after_process_hook
from worker.novel_sync import novel_sync_job
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
from worker.subscription_group import (
    check_subscription_group,
    subscription_scheduler,
)
from worker.tagging import tag_job
from worker.thumbhash_backfill import thumbhash_backfill_job
from worker.thumbnail import cover_thumbnail_job, thumbnail_job
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


async def _ensure_archive_table_schema() -> None:
    """Ensure all gallery-dl archive tables have the gallery_id FK column.

    Called at worker startup. Finds tables that gallery-dl auto-created
    without the Jyzrox extensions and ALTERs them to add gallery_id + created_at.
    """
    from sqlalchemy import text

    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
            SELECT t.table_name
            FROM information_schema.columns t
            WHERE t.column_name = 'entry'
              AND t.table_schema = 'public'
              AND t.table_name NOT IN (
                  SELECT table_name FROM information_schema.columns
                  WHERE column_name = 'gallery_id' AND table_schema = 'public'
              )
        """)
        )
        tables = [row[0] for row in result]
        for table in tables:
            col_count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.columns "
                        "WHERE table_name = :t AND table_schema = 'public'"
                    ),
                    {"t": table},
                )
            ).scalar()
            if col_count != 1:
                continue  # not a gallery-dl archive table (has more than just 'entry')
            await session.execute(
                text(f'''
                ALTER TABLE "{table}"
                ADD COLUMN IF NOT EXISTS gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS job_id UUID,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()
            ''')
            )
            logger.info("[archive] upgraded table '%s' with gallery_id FK", table)
        await session.commit()


async def _migrate_default_queue(r) -> None:
    """Move all jobs from the legacy 'default' queue to the correct new queues.

    Runs once on startup. Safe to call repeatedly (no-op if queue is empty).
    """
    import json

    from core.queue_config import JOB_QUEUE_ROUTING, QUEUE_INTERACTIVE

    queue_len = await r.llen("saq:default:queued")
    if queue_len == 0:
        return

    logger.info("[startup] Migrating %d jobs from legacy 'default' queue...", queue_len)
    old_keys = await r.lrange("saq:default:queued", 0, -1)
    migrated = 0

    for raw_key in old_keys:
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        try:
            job_data_raw = await r.get(key)
            if not job_data_raw:
                continue
            job_data = json.loads(job_data_raw)
            job_name = job_data.get("function", "")
            target = JOB_QUEUE_ROUTING.get(job_name, QUEUE_INTERACTIVE)
            new_key = key.replace("saq:job:default:", f"saq:job:{target}:", 1)
            job_data["queue"] = target
            await r.set(new_key, json.dumps(job_data))
            await r.rpush(f"saq:{target}:queued", new_key)
            if new_key != key:
                await r.delete(key)
            migrated += 1
        except Exception as exc:
            logger.warning("[startup] Could not migrate job %s: %s", key, exc)

    await r.delete("saq:default:queued")
    logger.info("[startup] Migrated %d / %d jobs from 'default' queue", migrated, len(old_keys))


async def startup(ctx: dict) -> None:
    logger.info("SAQ Worker started — Jyzrox")
    from core.redis_client import get_redis, init_redis

    await init_redis()
    r = get_redis()
    ctx["redis"] = r  # plain Redis client
    # Migrate any jobs left in the legacy 'default' queue (one-time, idempotent)
    await _migrate_default_queue(r)
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
    # Auto-upgrade archive tables created by gallery-dl without Jyzrox columns
    try:
        await _ensure_archive_table_schema()
    except Exception as exc:
        logger.warning("Archive table schema check failed (non-fatal): %s", exc)
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

    running_strategy = ((await r.get("setting:recovery_running")) or b"auto_retry").decode()
    paused_strategy = ((await r.get("setting:recovery_paused")) or b"keep_paused").decode()
    if running_strategy not in ("auto_retry", "mark_failed"):
        running_strategy = "auto_retry"
    if paused_strategy not in ("keep_paused", "auto_retry", "mark_failed"):
        paused_strategy = "keep_paused"
    recovery_counts = {
        "running_retried": 0,
        "running_failed": 0,
        "paused_kept": 0,
        "paused_retried": 0,
        "paused_failed": 0,
        "queued_requeued": 0,
    }

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

            # Re-enqueue or fail recovered jobs based on running_strategy
            for job in running_jobs:
                if running_strategy == "auto_retry":
                    job.retry_count = (job.retry_count or 0) + 1
                    job_key = compute_job_key(job.id, job.retry_count)
                    try:
                        await enqueue_download_job(job, job_key)
                        job.status = "queued"
                        job.error = None
                        job.finished_at = None
                        recovery_counts["running_retried"] += 1
                        logger.info("Re-enqueued recovered running job %s (retry=%d)", job.id, job.retry_count)
                    except Exception as exc:
                        job.status = "failed"
                        job.error = f"Re-enqueue failed on startup: {exc}"
                        job.finished_at = datetime.now(UTC)
                        logger.error("Failed to re-enqueue job %s: %s", job.id, exc)
                else:  # mark_failed
                    job.status = "failed"
                    job.error = "Marked failed by recovery policy"
                    job.finished_at = datetime.now(UTC)
                    recovery_counts["running_failed"] += 1
                    logger.info("Marked running job %s as failed (recovery policy=mark_failed)", job.id)
            await session.commit()
            logger.info("Recovered %d stale running jobs from previous worker session", len(running_jobs))

        # Re-enqueue stale "queued" jobs that survived a crash
        stale_queued = (
            (await session.execute(select(DownloadJob).where(DownloadJob.status == "queued"))).scalars().all()
        )
        if stale_queued:
            for job in stale_queued:
                job_key = compute_job_key(job.id, job.retry_count)
                try:
                    await enqueue_download_job(job, job_key)
                    recovery_counts["queued_requeued"] += 1
                    logger.info("Re-enqueued stale queued job %s", job.id)
                except Exception as exc:
                    job.status = "failed"
                    job.error = f"Re-enqueue failed on startup: {exc}"
                    job.finished_at = datetime.now(UTC)
                    logger.error("Failed to re-enqueue job %s: %s", job.id, exc)
            await session.commit()
            logger.info("Processed %d stale queued jobs", len(stale_queued))

        # Paused jobs: apply paused_strategy (keep_paused / auto_retry / mark_failed)
        # keep_paused: re-enqueue so SAQ result is written (pause gate catches them).
        # This ensures the resume endpoint can detect "coroutine dead" and re-enqueue properly.
        # Without this, resume after restart thinks the coroutine is alive and sets status
        # to "running" without re-enqueueing — leaving the job stuck forever.
        paused_jobs = (await session.execute(select(DownloadJob).where(DownloadJob.status == "paused"))).scalars().all()
        if paused_jobs:
            for job in paused_jobs:
                if paused_strategy == "keep_paused":
                    job_key = compute_job_key(job.id, job.retry_count)
                    try:
                        await enqueue_download_job(job, job_key)
                        recovery_counts["paused_kept"] += 1
                        logger.info("Re-enqueued paused job %s (pause gate will catch it)", job.id)
                    except Exception as exc:
                        logger.error("Failed to re-enqueue paused job %s: %s", job.id, exc)
                elif paused_strategy == "auto_retry":
                    await r.delete(f"download:pause:{job.id}")
                    job.retry_count = (job.retry_count or 0) + 1
                    job_key = compute_job_key(job.id, job.retry_count)
                    try:
                        await enqueue_download_job(job, job_key)
                        job.status = "queued"
                        job.error = None
                        job.finished_at = None
                        recovery_counts["paused_retried"] += 1
                        logger.info("Re-enqueued paused job %s as retry (retry=%d)", job.id, job.retry_count)
                    except Exception as exc:
                        job.status = "failed"
                        job.error = f"Re-enqueue failed on startup: {exc}"
                        job.finished_at = datetime.now(UTC)
                        logger.error("Failed to re-enqueue paused job %s: %s", job.id, exc)
                else:  # mark_failed
                    await r.delete(f"download:pause:{job.id}")
                    job.status = "failed"
                    job.error = "Marked failed by recovery policy"
                    job.finished_at = datetime.now(UTC)
                    recovery_counts["paused_failed"] += 1
                    logger.info("Marked paused job %s as failed (recovery policy=mark_failed)", job.id)
            await session.commit()
            logger.info(
                "Processed %d paused jobs from previous session (strategy=%s)", len(paused_jobs), paused_strategy
            )

        # Reset stuck subscription groups from previous worker session
        from db.models import SubscriptionGroup

        await session.execute(
            update(SubscriptionGroup).where(SubscriptionGroup.status == "running").values(status="idle")
        )
        await session.commit()
        logger.info("Reset stuck subscription groups to idle")

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SYSTEM_WORKER_RECOVERED,
        resource_type="system",
        running_strategy=running_strategy,
        paused_strategy=paused_strategy,
        **recovery_counts,
    )

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
        loop = asyncio.get_running_loop()

        def enqueue_sync(job_name: str, *args):
            import core.queue

            # Watcher passes: ("auto_discover_job",) or ("rescan_by_path_job", path)
            kwargs = {"dir_path": args[0]} if args else {}
            asyncio.run_coroutine_threadsafe(core.queue.enqueue(job_name, **kwargs), loop)

        _watcher.start(paths, enqueue_sync)
        await r.set(
            "watcher:status",
            json.dumps({"running": True, "paths": paths}),
        )

    # Jobs that were marked run_at_startup=True in the old config.
    import core.queue as _q

    await _q.enqueue("ehtag_sync_job")
    await _q.enqueue("disk_monitor_job")


async def shutdown(ctx: dict) -> None:
    logger.info("SAQ Worker shutting down")
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

        loop = asyncio.get_running_loop()

        def enqueue_sync(job_name: str, *args):
            import core.queue

            # Watcher passes: ("auto_discover_job",) or ("rescan_by_path_job", path)
            kwargs = {"dir_path": args[0]} if args else {}
            asyncio.run_coroutine_threadsafe(core.queue.enqueue(job_name, **kwargs), loop)

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
    except ValueError, TypeError:
        start_hour = 0

    try:
        end_hour = int(end_val) if end_val is not None else 6
    except ValueError, TypeError:
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
    except ValueError, TypeError:
        max_entries = 10000

    try:
        retention_days = int(retention_days_val) if retention_days_val is not None else 7
    except ValueError, TypeError:
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


async def memory_monitor_job(ctx: dict) -> dict:
    """Cron: warn when the worker container's memory use exceeds the alert threshold.

    Reads the worker's own cgroup v2 memory (the same figure ``docker stats``
    reports against the 2 GB limit) and logs a warning + emits an event when it
    crosses ``settings.memory_alert_pct``. Replaces the external memory_monitor.sh
    + CSV with an in-app, log-visible alert.
    """
    from core.config import settings
    from worker import memory as _mem

    mem = _mem.read_container_memory()
    if mem is None:
        return {"status": "unknown"}

    used_bytes, limit_bytes = mem
    used_mb = used_bytes / (1024 * 1024)
    limit_mb = limit_bytes / (1024 * 1024)
    pct = used_bytes / limit_bytes * 100
    threshold = settings.memory_alert_pct

    # DEBUG-only history recording (hardcoded switch, default off — see worker.memory).
    if _mem.MEMORY_HISTORY_ENABLED:
        samples = [("worker", round(used_mb, 1), round(limit_mb, 1), round(pct, 1))]
        host = _mem.read_host_memory()
        if host is not None:
            h_used, h_total = host
            samples.append(
                (
                    "host",
                    round(h_used / (1024 * 1024), 1),
                    round(h_total / (1024 * 1024), 1),
                    round(h_used / h_total * 100, 1),
                )
            )
        await _mem.persist_memory_history(samples)

    if pct >= threshold:
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.SYSTEM_MEMORY_HIGH,
            resource_type="system",
            used_mb=round(used_mb, 1),
            limit_mb=round(limit_mb, 1),
            pct=round(pct, 1),
            threshold_pct=threshold,
        )
        logger.warning(
            "[memory_monitor] HIGH: %.0f MB / %.0f MB (%.1f%%, threshold %.0f%%)",
            used_mb,
            limit_mb,
            pct,
            threshold,
        )
        return {"status": "high", "pct": round(pct, 1), "used_mb": round(used_mb, 1)}

    return {"status": "ok", "pct": round(pct, 1), "used_mb": round(used_mb, 1)}


async def adaptive_persist_job(ctx: dict) -> dict:
    """Persist dirty adaptive states from Redis to database."""
    from core.adaptive import adaptive_engine

    count = await adaptive_engine.persist_dirty()
    return {"persisted": count}


def _make_startup_log(label: str):
    async def _startup(ctx: dict) -> None:
        from core.redis_client import get_redis, init_redis

        try:
            r = get_redis()
        except RuntimeError:
            await init_redis()
            r = get_redis()
        ctx["redis"] = r
        logger.info("SAQ %s worker started", label)

    return _startup


_ingest_startup = _make_startup_log("ingest")
_render_startup = _make_startup_log("render")


# ── SAQ Worker Factory ───────────────────────────────────────────────


def _build_cron_jobs() -> list[CronJob]:
    """Build CronJob list from the scheduled task catalog."""
    func_map = {
        "scheduled_scan_job": scheduled_scan_job,
        "reconciliation_job": reconciliation_job,
        "database_backup_job": database_backup_job,
        "check_followed_artists": check_followed_artists,
        "dedup_tier1_job": dedup_tier1_job,
        "dedup_tier2_job": dedup_tier2_job,
        "dedup_tier3_job": dedup_tier3_job,
        "retry_failed_downloads_job": retry_failed_downloads_job,
        "ehtag_sync_job": ehtag_sync_job,
        "subscription_scheduler": subscription_scheduler,
        "rate_limit_schedule_job": rate_limit_schedule_job,
        "trash_gc_job": trash_gc_job,
        "log_cleanup_job": log_cleanup_job,
        "disk_monitor_job": disk_monitor_job,
        "memory_monitor_job": memory_monitor_job,
        "adaptive_persist_job": adaptive_persist_job,
        "novel_sync_job": novel_sync_job,
    }
    jobs = []
    for t in CATALOG:
        func = func_map.get(t.job_name)
        if func is None:
            raise RuntimeError(f"Catalog entry {t.task_id!r} references unknown job {t.job_name!r}")
        jobs.append(CronJob(func, cron=t.default_cron, unique=t.saq_unique, timeout=t.saq_timeout))
    return jobs


def build_workers() -> tuple:
    """Build and return all three SAQ Worker instances.

    Queue objects are pre-registered in core.queue._queues so that enqueue()
    works immediately from startup() onwards without a separate init call.
    """
    from saq import Queue, Worker

    import core.queue as _cq
    from core.queue_config import (
        ALL_QUEUES,
        DEFAULT_CONCURRENCY,
        QUEUE_INGEST,
        QUEUE_INTERACTIVE,
        QUEUE_RENDER,
    )

    # Build queue objects and pre-register for enqueue() routing
    queues = {name: Queue.from_url(settings.redis_url, name=name) for name in ALL_QUEUES}
    _cq._queues = queues

    concurrency = {
        QUEUE_INTERACTIVE: env_int("WORKER_CONCURRENCY_INTERACTIVE", DEFAULT_CONCURRENCY[QUEUE_INTERACTIVE]),
        QUEUE_INGEST: env_int("WORKER_CONCURRENCY_INGEST", DEFAULT_CONCURRENCY[QUEUE_INGEST]),
        QUEUE_RENDER: env_int("WORKER_CONCURRENCY_RENDER", DEFAULT_CONCURRENCY[QUEUE_RENDER]),
    }
    logger.info(
        "Worker concurrency — interactive: %d, ingest: %d, render: %d",
        concurrency[QUEUE_INTERACTIVE],
        concurrency[QUEUE_INGEST],
        concurrency[QUEUE_RENDER],
    )

    worker_interactive = Worker(
        queues[QUEUE_INTERACTIVE],
        functions=[
            download_job,
            import_job,
            batch_import_job,
            rescan_library_job,
            rescan_gallery_job,
            rescan_by_path_job,
            rescan_library_path_job,
            tag_job,
            reconciliation_job,
            scheduled_scan_job,
            toggle_watcher_job,
            check_followed_artists,
            check_single_subscription,
            check_subscription_group,
            dedup_tier1_job,
            dedup_tier2_job,
            dedup_tier3_job,
            dedup_scan_job,
            rate_limit_schedule_job,
            retry_failed_downloads_job,
            trash_gc_job,
            ehtag_sync_job,
            log_cleanup_job,
            database_backup_job,
            ("gdl_upgrade_job", gdl_upgrade_job),
            ("gdl_rollback_job", gdl_rollback_job),
            disk_monitor_job,
            memory_monitor_job,
            adaptive_persist_job,
            novel_sync_job,
        ],
        cron_jobs=_build_cron_jobs(),
        concurrency=concurrency[QUEUE_INTERACTIVE],
        startup=startup,
        shutdown=shutdown,
        after_process=after_process_hook,
    )

    worker_ingest = Worker(
        queues[QUEUE_INGEST],
        functions=[
            local_import_job,
            cover_thumbnail_job,
            auto_discover_job,
        ],
        concurrency=concurrency[QUEUE_INGEST],
        startup=_ingest_startup,
        after_process=after_process_hook,
    )

    worker_render = Worker(
        queues[QUEUE_RENDER],
        functions=[
            thumbnail_job,
            thumbhash_backfill_job,
        ],
        concurrency=concurrency[QUEUE_RENDER],
        startup=_render_startup,
        after_process=after_process_hook,
    )

    return worker_interactive, worker_ingest, worker_render


# Keep old name as alias for any external scripts that import it
build_worker = build_workers


__all__ = [
    "download_job",
    "import_job",
    "local_import_job",
    "batch_import_job",
    "rescan_library_job",
    "rescan_gallery_job",
    "rescan_by_path_job",
    "rescan_library_path_job",
    "auto_discover_job",
    "scheduled_scan_job",
    "cover_thumbnail_job",
    "thumbnail_job",
    "reconciliation_job",
    "tag_job",
    "check_followed_artists",
    "check_single_subscription",
    "check_subscription_group",
    "subscription_scheduler",
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
    "database_backup_job",
    "gdl_upgrade_job",
    "gdl_rollback_job",
    "disk_monitor_job",
    "memory_monitor_job",
    "adaptive_persist_job",
    "novel_sync_job",
    "startup",
    "shutdown",
    "build_workers",
    "build_worker",
    # Internal helpers re-exported for tests
    "_extract_tags",
    "_normalize_tags",
    "_build_gallery",
    "_upsert_tags",
    "_sha256",
    "compute_job_key",
    "enqueue_download_job",
]
