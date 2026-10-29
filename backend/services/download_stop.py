"""Stop & keep: a durable user intent to end a download and keep what it fetched.

Cancel is a rollback (the worker deletes the run). Stop records
``download_jobs.stop_requested_at`` and reuses the Redis cancel flag to end the
gallery-dl process, then the worker routes the result through its keep path
(drain -> import leftovers -> finalize -> subscription boundary). A job with no
live execution has nobody to do that, so a detached ``finalize_stopped_job``
task covers it.

The router and the worker both use this module; neither imports the other.
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import DownloadJob

logger = logging.getLogger(__name__)

# Value of the Redis cancel flag for a stop; cancel writes "1".
STOP_FLAG_VALUE = "stop"
_STOP_FLAG_TTL_S = 3600
# Hold the detached finalize back briefly: it is enqueued before the intent is
# committed (BE-T19), and a worker that ran it first would see no intent and
# ignore it for good.
_FINALIZE_DELAY_S = 5

_STOPPABLE_STATUSES = ("queued", "running", "paused")


class StopNotAllowed(Exception):
    """The job is already terminal, so there is nothing to stop."""

    def __init__(self, status: str):
        super().__init__(f"Cannot stop: status={status}")
        self.status = status


def _cancel_flag_key(job_id: uuid.UUID | str) -> str:
    return f"download:cancel:{job_id}"


async def request_stop(session: AsyncSession, job: DownloadJob) -> dict:
    """Record a stop intent for an active job and make its execution wind down.

    The decision is made in the database, not from the caller's ORM snapshot:
    one conditional UPDATE sets ``stop_requested_at`` only for an active job
    that has no intent yet, and its RETURNING row says whether the job has a
    live execution right now.

    * live execution (``admission_token`` set): only the intent and the Redis
      flag; the status stays active until the worker finishes the keep path, so
      duplicate/trash/purge guards keep seeing the job as running.
    * no live execution (queued, or paused after a restart): enqueue
      ``finalize_stopped_job`` before committing the intent (BE-T19).

    Idempotent: a job that already has an intent is reported as stopping.
    Raises StopNotAllowed for terminal (or vanished) jobs.
    """
    job_id = job.id  # a rollback below expires the instance
    result = await session.execute(
        update(DownloadJob)
        .where(
            DownloadJob.id == job_id,
            DownloadJob.status.in_(_STOPPABLE_STATUSES),
            DownloadJob.stop_requested_at.is_(None),
        )
        .values(stop_requested_at=datetime.now(UTC))
        .returning(DownloadJob.status, DownloadJob.admission_token)
    )
    claimed = result.first()

    if claimed is None:
        current = (
            await session.execute(
                select(DownloadJob.status, DownloadJob.stop_requested_at, DownloadJob.admission_token).where(
                    DownloadJob.id == job_id
                )
            )
        ).first()
        if current is None:
            raise StopNotAllowed("missing")
        if current.status not in _STOPPABLE_STATUSES:
            raise StopNotAllowed(current.status)
        if current.admission_token is not None:
            # Re-assert the flag: it is best-effort and may have been lost.
            await _set_stop_flag(job_id, best_effort=True)
        return {"status": current.status, "stopping": True}

    if claimed.admission_token is None:
        # Enqueue before commit: if the enqueue fails the UPDATE is rolled back
        # and the caller sees the error; an extra delivery is harmless (the
        # task ignores a job that is gone, has a live token, or has no intent).
        try:
            await core.queue.enqueue(
                "finalize_stopped_job",
                _job_id=f"stop:{job_id}:{uuid.uuid4()}",
                _timeout=settings.download_job_timeout,
                _scheduled=int(time.time()) + _FINALIZE_DELAY_S,
                db_job_id=str(job_id),
            )
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await _set_stop_flag(job_id)
    return {"status": claimed.status, "stopping": True}


async def _set_stop_flag(job_id: uuid.UUID | str, *, best_effort: bool = False) -> None:
    try:
        await get_redis().setex(_cancel_flag_key(job_id), _STOP_FLAG_TTL_S, STOP_FLAG_VALUE)
    except Exception as exc:
        if not best_effort:
            raise
        logger.warning("[download_stop] could not re-assert stop flag for %s: %s", job_id, exc)


async def read_stop_intent(job_id: str) -> str | None:
    """Authoritative intent from the DB: ``"cancel"``, ``"stop"`` or ``None``.

    Reads the row in its own session because the Redis flag is only a
    best-effort signal. Cancel outranks stop. Never raises: a lookup failure is
    logged and reported as no intent, so it cannot break the caller's finalize.
    """
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(str(job_id)))
            if job is None:
                return None
            if job.status == "cancelled":
                return "cancel"
            if job.stop_requested_at is not None:
                return "stop"
            return None
    except Exception as exc:  # noqa: BLE001 - must never block a worker finalize on a lookup error
        logger.error("[download_stop] failed to read stop intent for %s: %s", job_id, exc)
        return None
