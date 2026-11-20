"""Download job detail, pause/resume, cancel, stop and retry endpoints."""

import logging
import os
import signal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.database import get_db
from core.errors import api_error, parse_accept_language
from core.redis_client import get_redis
from db.models import DownloadJob, Gallery
from services.download_admission import next_admission_ticket
from services.download_enqueue import ACTIVE_JOB_STATUSES
from services.download_mode import (
    effective_mode,
    stop_discards,
)
from services.download_pause import PauseConflict, pause_job, resume_job
from services.download_presenter import serialize_download_job
from services.download_stop import StopNotAllowed, request_stop
from services.egress_persona import resolve_admission_key
from worker.helpers import compute_job_key, enqueue_download_job

logger = logging.getLogger(__name__)
router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class JobActionRequest(BaseModel):
    action: str  # "pause" or "resume"


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)
    gallery = None
    if job.gallery_id:
        gallery = await db.get(Gallery, job.gallery_id)
    return serialize_download_job(job, gallery)


@router.patch("/jobs/{job_id}")
async def pause_resume_job(
    job_id: uuid.UUID,
    body: JobActionRequest,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Pause or resume a running download job via Redis soft-pause key.

    The worker's pause_check callback reads download:pause:{job_id} from Redis
    and suspends iteration cooperatively. This works for all job types (gallery-dl
    subprocess and native plugin downloads) without relying on cross-container
    PID signalling, which is not possible since the api and worker containers have
    separate PID namespaces.
    """
    if body.action not in ("pause", "resume"):
        raise HTTPException(status_code=400, detail="action must be 'pause' or 'resume'")

    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    try:
        if body.action == "pause":
            return await pause_job(db, job)
        return await resume_job(db, job)
    except PauseConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Failed to re-enqueue job")


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    if job.status not in ("queued", "running", "paused"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel: status={job.status}")

    # A repair has nothing to roll back to: what it fetched is wanted, so cancel
    # acts as stop (the worker keeps the repaired files).
    if not stop_discards(effective_mode(job.mode, job.options)):
        try:
            return await request_stop(db, job)
        except StopNotAllowed as exc:
            raise HTTPException(status_code=400, detail=f"Cannot cancel: status={exc.status}") from exc

    # Decide in the database, not from the snapshot above: a worker (or a stop's
    # keep path, which claims the job `done` before keeping it) may have ended the
    # job since. The row lock this UPDATE takes is held until the commit below, so
    # a concurrent claim waits and then matches nothing.
    cancelled = (
        await db.execute(
            update(DownloadJob)
            .where(DownloadJob.id == job_id, DownloadJob.status.in_(ACTIVE_JOB_STATUSES))
            .values(status="cancelled")
            .returning(DownloadJob.id)
        )
    ).first()
    if cancelled is None:
        await db.rollback()
        current = (await db.execute(select(DownloadJob.status).where(DownloadJob.id == job_id))).scalar_one_or_none()
        raise HTTPException(status_code=400, detail=f"Cannot cancel: status={current}")

    # Kill the subprocess if it is running or paused
    redis = get_redis()
    pid_bytes = await redis.get(f"download:pid:{job_id}")
    if pid_bytes:
        try:
            pid = int(pid_bytes)
            # Verify PID belongs to gallery-dl before sending signal
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmdline = fh.read()
                if b"gallery-dl" not in cmdline:
                    logger.warning("[cancel] pid %d is not gallery-dl; skipping signal", pid)
                else:
                    os.kill(pid, signal.SIGTERM)
            except FileNotFoundError:
                pass  # Process already gone
        except (ValueError, PermissionError) as exc:
            logger.warning("[cancel] failed to kill pid %s: %s", pid_bytes, exc)
        await redis.delete(f"download:pid:{job_id}")

    # Also set Redis cancel flag for native downloads (no PID)
    await redis.setex(f"download:cancel:{job_id}", 3600, "1")

    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.DOWNLOAD_CANCELLED,
        actor_user_id=auth["user_id"],
        resource_type="download_job",
        resource_id=str(job_id),
    )
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/stop")
async def stop_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Stop a job and keep what it already fetched (cancel discards instead).

    Records a durable intent; the worker (or ``finalize_stopped_job`` for a job
    with no live execution) finishes it as ``done`` with ``outcome == "stopped"``
    and, for a subscription, moves the boundary to the run start. The status
    stays active until then.
    """
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    try:
        return await request_stop(db, job)
    except StopNotAllowed as exc:
        raise HTTPException(status_code=409, detail=f"Cannot stop: status={exc.status}") from exc


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Manually retry a failed or partial download job."""
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    # A stopped job was ended on purpose; replaying it with its original
    # options would fetch the history the user gave up (a first run has no
    # incremental cutoff).
    if getattr(job, "stop_requested_at", None) is not None:
        raise HTTPException(status_code=409, detail="Cannot retry a stopped job")
    if job.status not in ("failed", "partial"):
        raise HTTPException(status_code=400, detail=f"Cannot retry: status={job.status}")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=400, detail="Max retries reached")

    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)

    # Enqueue the SAQ job BEFORE committing the queued-state transition, so a
    # crash or enqueue failure after commit cannot orphan the job in "queued"
    # with no queue entry (edge case #36/#89). Mirrors the resume path. The job
    # key uses the post-increment retry_count, but enqueue_download_job() takes
    # the key explicitly and does not read retry_count, so we can enqueue before
    # mutating the row. On failure nothing is committed and the row stays
    # failed/partial with its original retry_count.
    new_retry_count = job.retry_count + 1
    job_key = compute_job_key(job.id, new_retry_count)
    try:
        await enqueue_download_job(job, job_key)
    except Exception as exc:
        logger.error("[retry] manual retry enqueue failed for %s: %s", job_id, exc)
        raise HTTPException(status_code=503, detail="Failed to enqueue retry job")

    job.retry_count = new_retry_count
    job.admission_ticket = await next_admission_ticket(db)
    job.admission_key = await resolve_admission_key(
        job.source, job.url, subscription_id=getattr(job, "subscription_id", None)
    )
    job.admission_token = None
    job.status = "queued"
    job.finished_at = None
    job.error = None

    # Read base_delay from Redis for backoff calculation
    redis = get_redis()
    base_delay_raw = await redis.get("setting:retry_base_delay_minutes")
    base_delay = int(base_delay_raw) if base_delay_raw else 5
    backoff_minutes = min(base_delay * (2**job.retry_count), 1440)
    job.next_retry_at = now + timedelta(minutes=backoff_minutes)

    await db.commit()

    return {"status": "queued", "retry_count": job.retry_count, "max_retries": job.max_retries}
