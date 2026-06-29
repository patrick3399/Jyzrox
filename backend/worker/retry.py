"""Retry failed/partial download jobs with exponential backoff."""

import logging
from datetime import UTC, datetime, timedelta

from saq.job import TERMINAL_STATUSES
from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.queue import get_queue
from core.queue_config import JOB_QUEUE_ROUTING, QUEUE_INTERACTIVE
from db.models import DownloadJob
from worker.constants import DISK_LOW_KEY
from worker.helpers import _cron_record, _cron_should_run, compute_job_key, enqueue_download_job

logger = logging.getLogger("worker")

_MAX_BACKOFF_MINUTES = 1440  # 24 hours cap


def _heartbeat_is_stale(last_update_at: str, threshold: datetime) -> bool:
    """Return True if a progress heartbeat is older than `threshold`.

    `last_update_at` is the ISO-8601 string written by the download worker's
    on_progress callback. A malformed/unparseable value is treated as stale so a
    job with a corrupt heartbeat is not left running forever.
    """
    try:
        hb = datetime.fromisoformat(last_update_at)
    except ValueError, TypeError:
        return True
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=UTC)
    return hb < threshold


async def retry_failed_downloads_job(ctx: dict) -> dict:
    """Cron job: retry failed/partial downloads with exponential backoff."""
    if not await _cron_should_run(ctx, "retry_downloads", "*/15 * * * *", True):
        return {"status": "skipped"}

    r = ctx["redis"]

    # Read settings from Redis
    enabled_raw = await r.get("setting:retry_enabled")
    if enabled_raw == b"0":
        await _cron_record(ctx, "retry_downloads", "disabled")
        return {"status": "disabled"}

    disk_low = await r.get(DISK_LOW_KEY)
    if disk_low:
        logger.info(
            "[retry] skipping — disk low (%s GB free)", disk_low.decode() if isinstance(disk_low, bytes) else disk_low
        )
        await _cron_record(ctx, "retry_downloads", "skipped_disk_low")
        return {"status": "skipped_disk_low"}

    # Operator-facing global cap. This is the live retry policy knob (settings
    # UI, validated 1-10). It is authoritative for the retry cron so that
    # raising OR lowering it takes effect immediately on existing jobs — the
    # per-job DownloadJob.max_retries column is only ever the DB default and is
    # never set per-job, so honoring the global is both correct and expected.
    max_retries_raw = await r.get("setting:retry_max_retries")
    max_retries = int(max_retries_raw) if max_retries_raw else 3

    base_delay_raw = await r.get("setting:retry_base_delay_minutes")
    base_delay = int(base_delay_raw) if base_delay_raw else 5

    retried = 0
    skipped = 0

    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(UTC)

            # ── Stale reaper: detect zombie jobs ──────────────────────────
            # A running job is only stale if its progress HEARTBEAT
            # (progress.last_update_at, written by on_progress every tick) has
            # gone quiet for 60+ minutes — NOT merely because created_at is old.
            # A long but actively-downloading job keeps a fresh heartbeat and
            # must be left alone (edge case #33). created_at < now-1h is a cheap,
            # lossless coarse pre-filter: a job created within the last hour
            # cannot have a heartbeat older than an hour.
            stale_threshold = now - timedelta(hours=1)
            running_candidates = (
                (
                    await session.execute(
                        select(DownloadJob).where(
                            DownloadJob.status == "running",
                            DownloadJob.created_at < stale_threshold,
                        )
                    )
                )
                .scalars()
                .all()
            )
            stale_running_ids = []
            for job in running_candidates:
                last_update = (job.progress or {}).get("last_update_at")
                if last_update and not _heartbeat_is_stale(last_update, stale_threshold):
                    continue  # actively progressing — leave it running
                job.status = "failed"
                job.error = "Stale: no progress for 60+ minutes"
                job.finished_at = now
                stale_running_ids.append(job.id)
                logger.warning("[stale-reaper] marked running job %s as failed (no progress update)", job.id)

            # Stale reaper: queued jobs stuck for 30+ minutes.
            # A queued DB row is only stale if it has NO live SAQ entry. Failing a
            # legitimately-waiting backlog job (low concurrency / source-semaphore
            # wait) and then retrying it in the same run produces duplicate SAQ
            # queue entries (edge case #34). created_at < now-30min stays as a
            # cheap coarse pre-filter; the SAQ-membership check is authoritative.
            queued_candidates = (
                (
                    await session.execute(
                        select(DownloadJob).where(
                            DownloadJob.status == "queued",
                            DownloadJob.created_at < now - timedelta(minutes=30),
                        )
                    )
                )
                .scalars()
                .all()
            )
            stale_queued_ids = []
            download_queue = None
            if queued_candidates:
                try:
                    download_queue = get_queue(JOB_QUEUE_ROUTING.get("download_job", QUEUE_INTERACTIVE))
                except RuntimeError:
                    # Queues not initialized in this context — cannot verify SAQ
                    # membership, so skip queued reaping (preserve, the safe side).
                    download_queue = None
            for job in queued_candidates:
                if download_queue is None:
                    continue
                saq_job = await download_queue.job(compute_job_key(job.id, job.retry_count))
                if saq_job is not None and saq_job.status not in TERMINAL_STATUSES:
                    continue  # still live in SAQ — legitimately waiting, not stale
                job.status = "failed"
                job.error = "Stale: queued 30+ minutes with no active queue entry"
                job.finished_at = now
                stale_queued_ids.append(job.id)
                logger.warning("[stale-reaper] marked queued job %s as failed (no live SAQ entry)", job.id)

            stale_count = len(stale_running_ids) + len(stale_queued_ids)
            if stale_count > 0:
                await session.flush()
                logger.info("[stale-reaper] marked %d stale jobs as failed", stale_count)

            # ── Retry: re-enqueue failed/partial jobs ──────────────────────────
            stmt = (
                select(DownloadJob)
                .where(
                    DownloadJob.status.in_(["failed", "partial"]),
                    DownloadJob.retry_count < max_retries,
                )
                .where(
                    (DownloadJob.next_retry_at == None) | (DownloadJob.next_retry_at <= now)  # noqa: E711
                )
                .order_by(DownloadJob.created_at.asc())
                .limit(10)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            jobs = result.scalars().all()

            for job in jobs:
                job.retry_count += 1
                job.status = "queued"
                job.finished_at = None
                job.error = None

                # Compute next_retry_at for if THIS retry also fails
                backoff_minutes = min(base_delay * (2**job.retry_count), _MAX_BACKOFF_MINUTES)
                job.next_retry_at = now + timedelta(minutes=backoff_minutes)

                job_key = compute_job_key(job.id, job.retry_count)
                try:
                    await enqueue_download_job(job, job_key)
                    retried += 1
                    logger.info(
                        "[retry] re-queued job %s (attempt %d/%d)",
                        job.id,
                        job.retry_count,
                        max_retries,
                    )
                except Exception as exc:
                    # Revert if enqueue fails
                    job.retry_count -= 1
                    job.status = "failed"
                    job.error = f"Retry enqueue failed: {exc}"
                    skipped += 1
                    logger.error("[retry] failed to enqueue job %s: %s", job.id, exc)

            await session.commit()

        status_msg = f"retried={retried}, skipped={skipped}, stale_reaped={stale_count}"
        await _cron_record(ctx, "retry_downloads", "ok" if retried > 0 or stale_count > 0 else "idle", None)
        logger.info("[retry] done: %s", status_msg)
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.RETRY_PROCESSED,
            resource_type="system",
            retried=retried,
            skipped=skipped,
            stale_reaped=stale_count,
        )
        return {"status": "ok", "retried": retried, "skipped": skipped, "stale_reaped": stale_count}

    except Exception as exc:
        logger.error("[retry] cron error: %s", exc, exc_info=True)
        await _cron_record(ctx, "retry_downloads", "error", str(exc))
        return {"status": "error", "error": str(exc)}
