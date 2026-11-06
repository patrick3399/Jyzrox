"""Per-job pause/resume shared by the download router and subscription pause."""

import uuid

from saq.job import TERMINAL_STATUSES as SAQ_TERMINAL_STATUSES
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.redis_client import get_redis
from db.models import DownloadJob
from services.download_admission import next_admission_ticket
from services.egress_persona import resolve_admission_key

PAUSE_KEY_TTL = 86400
_TERMINAL = frozenset({"done", "failed", "cancelled", "partial"})


class PauseConflict(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def pause_key(job_id) -> str:
    return f"download:pause:{job_id}"


# Imported after the names above on purpose: worker.helpers -> worker/__init__ ->
# worker.download imports PAUSE_KEY_TTL/pause_key from this module, so they must
# already exist when this module is only partially initialised.
from worker.helpers import compute_job_key, enqueue_download_job  # noqa: E402


async def pause_job(db: AsyncSession, job: DownloadJob) -> dict:
    """Soft-pause a job via the Redis key the worker's pause_check reads.

    This works for all job types (gallery-dl subprocess and native plugin
    downloads) without cross-container PID signalling, which is not possible
    since the api and worker containers have separate PID namespaces.
    """
    if job.status in _TERMINAL:
        raise PauseConflict(f"Job already {job.status}")
    if job.status == "paused":
        # Already in the desired state — no-op, return current status
        return {"status": job.status}
    # job.status == "running" — valid transition
    await get_redis().set(pause_key(job.id), b"1", ex=PAUSE_KEY_TTL)  # 24h TTL as safety net
    job.status = "paused"
    await db.commit()
    return {"status": job.status}


async def resume_job(db: AsyncSession, job: DownloadJob) -> dict:
    if job.status in _TERMINAL:
        raise PauseConflict(f"Job already {job.status}")
    if job.status == "running":
        # Already in the desired state — no-op, return current status
        return {"status": job.status}
    # job.status == "paused" or "queued" — valid transition
    await get_redis().delete(pause_key(job.id))

    # A token proves that a live execution owns this job. Token-less paused
    # rows need a fresh transport delivery and FIFO ticket; this is not a
    # failed business attempt and must not consume retry_count.
    if job.admission_token is not None:
        job.status = "running"
        await db.commit()
        return {"status": job.status}

    # Compatibility for a pre-admission coroutine during a rolling
    # upgrade. Migrated/new rows always have a ticket; only a legacy row
    # without one may trust the old SAQ active state.
    if job.admission_ticket is None:
        legacy_key = compute_job_key(job.id, job.retry_count)
        legacy_saq_job = await core.queue.get_queue().job(legacy_key)
        if legacy_saq_job is not None and legacy_saq_job.status not in SAQ_TERMINAL_STATUSES:
            job.status = "running"
            await db.commit()
            return {"status": job.status}

    # Legacy rows may still have an active SAQ coroutine but no token. It
    # cannot safely resume under the fenced admission contract, so enqueue
    # a fresh uniquely keyed attempt.
    # SAQ exposes job state via queue.job(key); a None return means the job
    # has been cleared from Redis (e.g. TTL expired or never enqueued).
    new_saq_key = f"dispatch:{job.id}:{uuid.uuid4()}"
    try:
        await enqueue_download_job(job, new_saq_key)  # BE-T19: before commit
    except Exception as exc:
        raise RuntimeError("Failed to re-enqueue job") from exc

    job.admission_ticket = await next_admission_ticket(db)
    job.admission_key = await resolve_admission_key(job.source, job.url, subscription_id=job.subscription_id)
    job.admission_token = None
    job.status = "queued"
    job.error = None
    job.finished_at = None
    await db.commit()
    return {"status": "queued", "restarted": True}
