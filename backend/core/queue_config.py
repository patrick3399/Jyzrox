"""Job queue routing configuration — single source of truth.

To change which queue a job runs on, or tune concurrency defaults,
edit only this file. core/queue.py and worker/__init__.py import from here.
"""

# ── Queue names ──────────────────────────────────────────────────────────────
QUEUE_INTERACTIVE = "interactive"   # user-triggered actions + cron
QUEUE_INGEST = "ingest"             # import pipeline stages 1–2
QUEUE_RENDER = "render"             # CPU-bound bulk image processing

ALL_QUEUES: tuple[str, ...] = (QUEUE_INTERACTIVE, QUEUE_INGEST, QUEUE_RENDER)

# ── Job → queue routing ───────────────────────────────────────────────────────
# Jobs NOT listed here default to QUEUE_INTERACTIVE at every enqueue() call.
#
# Priority reference (higher = more urgent; determines queue assignment):
#
#   interactive (95–5):  user-triggered + cron/maintenance
#   ingest      (40–30): import pipeline, prerequisite for gallery display
#   render      (15–10): CPU-bound bulk image processing, always yields
#
# job_name                    queue            priority  notes
# ─────────────────────────────────────────────────────────────────────────────
# download_job (manual)       interactive       95       user waiting
# import_job                  interactive       90       post-download
# batch_import_job            interactive       85
# check_single_subscription   interactive       80
# check_followed_artists      interactive       75
# check_subscription_group    interactive       75
# rescan_gallery_job          interactive       70
# tag_job                     interactive       70
# download_job (subscription) interactive       65       via subscription_id
# dedup_scan_job              interactive       60
# dedup_tier1/2/3_job         interactive       55
# subscription_scheduler      interactive       50       cron, must be on-time
# retry_failed_downloads      interactive       45       cron
# rescan_library_job          interactive       45
# gdl_upgrade/rollback        interactive       40
# disk_monitor_job            interactive       35       cron
# adaptive_persist_job        interactive       30       cron
# rate_limit_schedule_job     interactive       25       cron
# scheduled_scan_job          interactive       20       cron
# ehtag_sync_job              interactive        8       cron, daily
# log_cleanup_job             interactive        8       cron
# trash_gc_job                interactive        8       cron
# reconciliation_job          interactive        5       cron, weekly
# ─────────────────────────────────────────────────────────────────────────────
# local_import_job            ingest            40       creates images/pages
# cover_thumbnail_job         ingest            35       single cover, fast
# auto_discover_job           ingest            30       triggers local_import
# ─────────────────────────────────────────────────────────────────────────────
# thumbnail_job               render            15       full-book thumbnails
# thumbhash_backfill_job      render            10       batch maintenance
# ─────────────────────────────────────────────────────────────────────────────

JOB_QUEUE_ROUTING: dict[str, str] = {
    # render — CPU-bound, lowest priority
    "thumbnail_job":            QUEUE_RENDER,
    "thumbhash_backfill_job":   QUEUE_RENDER,
    # ingest — import pipeline, must precede render
    "local_import_job":         QUEUE_INGEST,
    "cover_thumbnail_job":      QUEUE_INGEST,
    "auto_discover_job":        QUEUE_INGEST,
    # everything else → QUEUE_INTERACTIVE (default)
}

# ── Default concurrency per queue ────────────────────────────────────────────
# Override at runtime via environment variables:
#   WORKER_CONCURRENCY_INTERACTIVE  (default 6)
#   WORKER_CONCURRENCY_INGEST       (default 4)
#   WORKER_CONCURRENCY_RENDER       (default 2)
#
DEFAULT_CONCURRENCY: dict[str, int] = {
    QUEUE_INTERACTIVE: 6,   # I/O-bound; high concurrency is safe
    QUEUE_INGEST:      4,   # mixed disk I/O
    QUEUE_RENDER:      2,   # CPU-bound; limited by core count
}
