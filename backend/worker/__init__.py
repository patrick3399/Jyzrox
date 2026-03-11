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

from arq.connections import RedisSettings
from arq.cron import cron

from core.config import get_all_library_paths, settings
from core.redis_client import close_redis, init_redis
from core.watcher import LibraryWatcher

from worker.download import download_job
from worker.importer import (
    import_job,
    local_import_job,
    batch_import_job,
    _extract_tags,
    _normalize_tags,
    _build_gallery,
    _upsert_tags,
)
from worker.scan import (
    rescan_library_job,
    rescan_gallery_job,
    rescan_by_path_job,
    rescan_library_path_job,
    auto_discover_job,
    scheduled_scan_job,
)
from worker.thumbnail import thumbnail_job
from worker.reconciliation import reconciliation_job
from worker.tagging import tag_job
from worker.subscription import (
    check_followed_artists,
    check_single_subscription,
)
from worker.dedup_tier1 import dedup_tier1_job
from worker.dedup_tier2 import dedup_tier2_job
from worker.dedup_tier3 import dedup_tier3_job
from worker.dedup_scan import dedup_scan_job
from worker.helpers import _sha256

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


# ── Lifecycle ────────────────────────────────────────────────────────

_watcher = LibraryWatcher()


async def startup(ctx: dict) -> None:
    logger.info("ARQ Worker started — Jyzrox")
    await init_redis()
    from plugins import init_plugins
    await init_plugins()
    r = ctx["redis"]
    for key in ("download:sem:ehentai", "download:sem:pixiv", "download:sem:other"):
        await r.delete(key)
    # Clean up stale scan progress from previous runs
    await r.delete(
        "rescan:progress", "rescan:cancel",
        "dedup:progress:status", "dedup:progress:signal",
        "dedup:progress:current", "dedup:progress:total",
        "dedup:progress:tier", "dedup:progress:mode",
    )

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
            asyncio.run_coroutine_threadsafe(
                arq_pool.enqueue_job(job_name, *args), loop
            )

        _watcher.start(paths, enqueue_sync)
        await r.set(
            "watcher:status",
            json.dumps({"running": True, "paths": paths}),
        )


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ Worker shutting down")
    _watcher.stop()
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
            asyncio.run_coroutine_threadsafe(
                arq_pool.enqueue_job(job_name, *args), loop
            )

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


# ── ARQ Worker Settings ──────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        download_job,
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
    ]
    cron_jobs = [
        cron(
            scheduled_scan_job,
            hour=None,   # every hour
            minute=0,    # at :00
            run_at_startup=False,
            unique=True,
            timeout=7200,
        ),
        cron(
            reconciliation_job,
            weekday=0,   # Monday
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
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = int(os.environ.get("MAX_WORKER_JOBS", "8"))
    job_timeout = 3600


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
    "startup",
    "shutdown",
    "WorkerSettings",
    # Internal helpers re-exported for tests
    "_extract_tags",
    "_normalize_tags",
    "_build_gallery",
    "_upsert_tags",
    "_sha256",
]
