"""Retry failed/partial download jobs with exponential backoff."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from core.database import AsyncSessionLocal
from db.models import DownloadJob
from worker.constants import DISK_LOW_KEY
from worker.helpers import _cron_record, _cron_should_run, compute_job_key, enqueue_download_job

logger = logging.getLogger("worker")

_MAX_BACKOFF_MINUTES = 1440  # 24 hours cap


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

    max_retries_raw = await r.get("setting:retry_max_retries")
    max_retries = int(max_retries_raw) if max_retries_raw else 3  # noqa: F841

    base_delay_raw = await r.get("setting:retry_base_delay_minutes")
    base_delay = int(base_delay_raw) if base_delay_raw else 5

    retried = 0
    skipped = 0

    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(UTC)

            # ── Stale reaper: detect zombie jobs ──────────────────────────
            # Running jobs created 60+ minutes ago with no completion (no finished_at)
            stale_running_result = await session.execute(
                update(DownloadJob)
                .where(
                    DownloadJob.status == "running",
                    DownloadJob.created_at < now - timedelta(hours=1),
                )
                .values(
                    status="failed",
                    error="Stale: no progress for 60+ minutes",
                    finished_at=now,
                )
                .returning(DownloadJob.id)
            )
            stale_running_ids = stale_running_result.scalars().all()
            for sid in stale_running_ids:
                logger.warning("[stale-reaper] marked running job %s as failed (no progress update)", sid)

            # Stale reaper: queued jobs stuck for 30+ minutes
            stale_queued_result = await session.execute(
                update(DownloadJob)
                .where(
                    DownloadJob.status == "queued",
                    DownloadJob.created_at < now - timedelta(minutes=30),
                )
                .values(
                    status="failed",
                    error="Stale: queued for 30+ minutes without starting",
                    finished_at=now,
                )
                .returning(DownloadJob.id)
            )
            stale_queued_ids = stale_queued_result.scalars().all()
            for sid in stale_queued_ids:
                logger.warning("[stale-reaper] marked queued job %s as failed (stuck in queue)", sid)

            stale_count = len(stale_running_ids) + len(stale_queued_ids)
            if stale_count > 0:
                await session.flush()
                logger.info("[stale-reaper] marked %d stale jobs as failed", stale_count)

            # ── Retry: re-enqueue failed/partial jobs ──────────────────────────
            stmt = (
                select(DownloadJob)
                .where(
                    DownloadJob.status.in_(["failed", "partial"]),
                    DownloadJob.retry_count < DownloadJob.max_retries,
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
                        job.max_retries,
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
