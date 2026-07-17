"""Scheduled task catalog — single source of truth for all scheduled tasks.

Both the admin API router and the SAQ worker consume this module so that task
metadata, default cron expressions, and timeouts are defined exactly once.

Limitation (#23): The Redis-stored cron_expr (user-editable via the UI) acts as
a GATE interval inside _cron_should_run(), not as the actual SAQ wake-up
schedule. SAQ fires at default_cron; the Redis value only controls whether the
job proceeds. Changing the UI cron narrows/widens the gate but does not change
how often SAQ wakes the function. Fixing this would require rebuilding SAQ
Worker objects at runtime, which is out of scope for this catalog refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import settings


@dataclass
class ScheduledTaskDef:
    task_id: str
    name: str
    description: str
    job_name: str
    default_cron: str
    default_enabled: bool
    saq_timeout: int
    configurable: bool = True
    manual_kwargs: dict[str, Any] = field(default_factory=dict)
    manual_timeout: int | None = None
    progress_key: str | None = None
    saq_unique: bool = True

    def __post_init__(self) -> None:
        if self.manual_timeout is None:
            self.manual_timeout = self.saq_timeout


# ── Ordered catalog ────────────────────────────────────────────────────────
# configurable=True  → visible in admin scheduled-tasks UI
# configurable=False → background-only, not user-facing
CATALOG: list[ScheduledTaskDef] = [
    # ── User-configurable ─────────────────────────────────────────────────
    ScheduledTaskDef(
        task_id="library_scan",
        name="External Folder Scan",
        description="Scan external folders and update linked local galleries",
        job_name="scheduled_scan_job",
        default_cron="0 * * * *",
        default_enabled=True,
        saq_timeout=7200,
        manual_kwargs={"force": True},
        manual_timeout=7200,
        progress_key="rescan:progress",
    ),
    ScheduledTaskDef(
        task_id="reconciliation",
        name="Reconciliation",
        description="Verify database/filesystem consistency and clean orphaned blobs",
        job_name="reconciliation_job",
        default_cron="0 3 * * 1",
        default_enabled=True,
        saq_timeout=3600,
        manual_kwargs={"force": True},
        manual_timeout=3600,
        progress_key="reconcile:progress",
    ),
    ScheduledTaskDef(
        task_id="database_backup",
        name="Database Backup",
        description="Create a compressed PostgreSQL dump for disaster recovery",
        job_name="database_backup_job",
        default_cron="0 2 * * *",
        default_enabled=True,
        saq_timeout=settings.backup_pg_dump_timeout,
        manual_kwargs={"force": True},
        manual_timeout=settings.backup_pg_dump_timeout,
        progress_key="backup:database:claim",
    ),
    ScheduledTaskDef(
        task_id="check_subscriptions",
        name="Check Subscriptions",
        description="Check followed artists and subscriptions for new works",
        job_name="check_followed_artists",
        default_cron="30 */2 * * *",
        default_enabled=True,
        saq_timeout=3600,
    ),
    ScheduledTaskDef(
        task_id="dedup_tier1",
        name="Dedup — pHash Scan",
        description="Scan all images for similar pairs using perceptual hashing",
        job_name="dedup_tier1_job",
        default_cron="0 8 * * *",
        default_enabled=False,
        saq_timeout=14400,
        manual_kwargs={"force": True},
    ),
    ScheduledTaskDef(
        task_id="dedup_tier2",
        name="Dedup — Heuristic Classify",
        description="Classify similar pairs by resolution and file size",
        job_name="dedup_tier2_job",
        default_cron="0 9 * * *",
        default_enabled=False,
        saq_timeout=3600,
        manual_kwargs={"force": True},
    ),
    ScheduledTaskDef(
        task_id="dedup_tier3",
        name="Dedup — OpenCV Verify",
        description="Pixel-level validation of similar pairs (CPU intensive, runs nightly)",
        job_name="dedup_tier3_job",
        default_cron="0 2 * * *",
        default_enabled=False,
        saq_timeout=7200,
        manual_kwargs={"force": True},
    ),
    ScheduledTaskDef(
        task_id="retry_downloads",
        name="Retry Failed Downloads",
        description="Auto-retry failed and partial downloads with exponential backoff",
        job_name="retry_failed_downloads_job",
        default_cron="*/15 * * * *",
        default_enabled=True,
        saq_timeout=300,
    ),
    ScheduledTaskDef(
        task_id="ehtag_sync",
        name="EhTag Translation Sync",
        description="Sync tag translations from EhTagTranslation database (CDN)",
        job_name="ehtag_sync_job",
        # Fixed: was "30 4 * * *" (daily) in SAQ but "0 4 * * 0" (weekly) in
        # the UI default and in _cron_should_run. Aligned to weekly so SAQ
        # wake-up matches the gate interval. See edge-case audit #26.
        default_cron="0 4 * * 0",
        default_enabled=True,
        saq_timeout=300,
    ),
    # ── Background-only (not shown in admin UI) ───────────────────────────
    ScheduledTaskDef(
        task_id="subscription_scheduler",
        name="Subscription Scheduler",
        description="Manage subscription group scheduling (internal, high-frequency)",
        job_name="subscription_scheduler",
        default_cron="* * * * *",
        default_enabled=True,
        saq_timeout=120,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="rate_limit_schedule",
        name="Rate Limit Scheduler",
        description="Persist adaptive rate-limit adjustments to Redis",
        job_name="rate_limit_schedule_job",
        default_cron="*/10 * * * *",
        default_enabled=True,
        saq_timeout=60,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="trash_gc",
        name="Trash GC",
        description="Permanently delete expired trash items",
        job_name="trash_gc_job",
        default_cron="0 4 * * *",
        default_enabled=True,
        saq_timeout=3600,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="log_cleanup",
        name="Log Cleanup",
        description="Remove stale event log entries",
        job_name="log_cleanup_job",
        default_cron="30 3 * * *",
        default_enabled=True,
        saq_timeout=300,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="disk_monitor",
        name="Disk Monitor",
        description="Check available disk space and emit alerts",
        job_name="disk_monitor_job",
        default_cron="*/5 * * * *",
        default_enabled=True,
        saq_timeout=30,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="memory_monitor",
        name="Memory Monitor",
        description="Check worker container memory usage and emit alerts when high",
        job_name="memory_monitor_job",
        default_cron="*/5 * * * *",
        default_enabled=True,
        saq_timeout=30,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="adaptive_persist",
        name="Adaptive State Persist",
        description="Flush adaptive download rate state to Redis",
        job_name="adaptive_persist_job",
        default_cron="*/5 * * * *",
        default_enabled=True,
        saq_timeout=60,
        configurable=False,
    ),
    ScheduledTaskDef(
        task_id="novel_git_sync",
        name="Novel Git Sync",
        description="Fetch + fast-forward pull the novel repo and retry unpushed commits",
        job_name="novel_sync_job",
        default_cron="*/15 * * * *",
        default_enabled=True,
        saq_timeout=120,
    ),
    ScheduledTaskDef(
        task_id="novel_index",
        name="Novel Knowledge Index",
        description="Rebuild novel notes/links/mentions index from the working tree",
        job_name="novel_index_job",
        default_cron="0 4 * * *",
        default_enabled=True,
        saq_timeout=300,
    ),
]

# ── Lookup helpers ─────────────────────────────────────────────────────────
CONFIGURABLE_TASK_DEFS: dict[str, ScheduledTaskDef] = {t.task_id: t for t in CATALOG if t.configurable}
