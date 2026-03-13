"""Retry failed/partial download jobs with exponential backoff."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.database import AsyncSessionLocal
from db.models import DownloadJob
from worker.helpers import _cron_record, _cron_should_run

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

    max_retries_raw = await r.get("setting:retry_max_retries")
    max_retries = int(max_retries_raw) if max_retries_raw else 3

    base_delay_raw = await r.get("setting:retry_base_delay_minutes")
    base_delay = int(base_delay_raw) if base_delay_raw else 5

    retried = 0
    skipped = 0

    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(UTC)
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
                backoff_minutes = min(base_delay * (2 ** job.retry_count), _MAX_BACKOFF_MINUTES)
                job.next_retry_at = now + timedelta(minutes=backoff_minutes)

                # Enqueue ARQ job with unique ID to avoid cache conflicts
                arq_job_id = f"retry:{job.id}:{job.retry_count}"
                try:
                    await r.enqueue_job(
                        "download_job",
                        job.url,
                        job.source or "",
                        None,  # options
                        str(job.id),
                        job.progress.get("total") if job.progress else None,
                        _job_id=arq_job_id,
                    )
                    retried += 1
                    logger.info(
                        "[retry] re-queued job %s (attempt %d/%d)",
                        job.id, job.retry_count, job.max_retries,
                    )
                except Exception as exc:
                    # Revert if enqueue fails
                    job.retry_count -= 1
                    job.status = "failed"
                    job.error = f"Retry enqueue failed: {exc}"
                    skipped += 1
                    logger.error("[retry] failed to enqueue job %s: %s", job.id, exc)

            await session.commit()

        status_msg = f"retried={retried}, skipped={skipped}"
        await _cron_record(ctx, "retry_downloads", "ok" if retried > 0 else "idle", None)
        logger.info("[retry] done: %s", status_msg)
        return {"status": "ok", "retried": retried, "skipped": skipped}

    except Exception as exc:
        logger.error("[retry] cron error: %s", exc, exc_info=True)
        await _cron_record(ctx, "retry_downloads", "error", str(exc))
        return {"status": "error", "error": str(exc)}
