"""Download queue management."""

import logging
import os
import signal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from core.redis_client import get_redis
from db.models import DownloadJob

logger = logging.getLogger(__name__)
router = APIRouter(tags=["download"])


class DownloadRequest(BaseModel):
    url: str
    source: str = ""  # ignored; kept for backward compat
    options: dict | None = None  # ignored; kept for backward compat
    total: int | None = None


class JobActionRequest(BaseModel):
    action: str  # "pause" or "resume"


def _detect_source(url: str) -> str:
    """Auto-detect source from URL domain."""
    if "pixiv.net" in url:
        return "pixiv"
    if "e-hentai.org" in url or "exhentai.org" in url:
        return "ehentai"
    return "unknown"


@router.post("/")
async def enqueue_download(
    req: DownloadRequest,
    request: Request,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a DB download record and enqueue an ARQ job.

    Order: ARQ enqueue first, then DB commit. If ARQ fails we never create the
    DB record. If DB insert fails after a successful ARQ enqueue we log a
    warning — the ARQ job will time out naturally without a matching DB record.
    """
    job_id = uuid.uuid4()
    source = _detect_source(req.url)
    initial_progress = {"total": req.total} if req.total is not None else None

    # 1. Enqueue ARQ job first — if this fails, no DB record is created.
    arq = request.app.state.arq
    try:
        await arq.enqueue_job(
            "download_job",
            req.url,
            source,
            req.options,
            str(job_id),
            req.total,
            _job_id=str(job_id),
        )
    except Exception as exc:
        logger.error("[enqueue] ARQ enqueue failed: %s", exc)
        raise HTTPException(status_code=503, detail="Failed to enqueue download job")

    # 2. Persist DB record. If this fails, log a warning; the ARQ job will
    #    eventually time out without a matching DB row.
    try:
        job = DownloadJob(id=job_id, url=req.url, source=source, status="queued", progress=initial_progress)
        db.add(job)
        await db.commit()
    except Exception as exc:
        logger.warning(
            "[enqueue] ARQ job %s enqueued but DB insert failed: %s — job will time out naturally",
            job_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Job enqueued but failed to persist to database")

    return {"job_id": str(job_id), "status": "queued"}


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DownloadJob)
    if status:
        stmt = stmt.where(DownloadJob.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()

    return {"total": total, "jobs": [_j(j) for j in jobs]}


@router.delete("/jobs")
async def clear_finished_jobs(
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete all completed, failed, and cancelled jobs."""
    stmt = delete(DownloadJob).where(
        DownloadJob.status.in_(["done", "failed", "cancelled"])
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/stats")
async def get_stats(
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return counts of running and finished jobs for nav badge polling."""
    running_count = (
        await db.execute(
            select(func.count()).where(DownloadJob.status.in_(["queued", "running", "paused"]))
        )
    ).scalar_one()
    finished_count = (
        await db.execute(
            select(func.count()).where(DownloadJob.status.in_(["done", "failed", "cancelled"]))
        )
    ).scalar_one()
    return {"running": running_count, "finished": finished_count}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _j(job)


@router.patch("/jobs/{job_id}")
async def pause_resume_job(
    job_id: uuid.UUID,
    body: JobActionRequest,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Pause or resume a running download job via SIGSTOP/SIGCONT."""
    if body.action not in ("pause", "resume"):
        raise HTTPException(status_code=400, detail="action must be 'pause' or 'resume'")

    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    redis = get_redis()
    pid_bytes = await redis.get(f"download:pid:{job_id}")
    if not pid_bytes:
        raise HTTPException(status_code=400, detail="Pause/resume not supported for this download type")

    try:
        pid = int(pid_bytes)
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Corrupted PID value in Redis")

    # Validate that the PID actually belongs to a gallery-dl process before signalling.
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmdline = fh.read()
        if b"gallery-dl" not in cmdline:
            logger.warning("[pause_resume] pid %d cmdline does not contain gallery-dl; clearing stale PID", pid)
            await redis.delete(f"download:pid:{job_id}")
            raise HTTPException(status_code=400, detail="Process is no longer a gallery-dl process")
    except FileNotFoundError:
        await redis.delete(f"download:pid:{job_id}")
        raise HTTPException(status_code=400, detail="Process no longer exists")

    try:
        if body.action == "pause":
            if job.status != "running":
                raise HTTPException(status_code=400, detail=f"Cannot pause: status={job.status}")
            os.kill(pid, signal.SIGSTOP)
            job.status = "paused"
        else:  # resume
            if job.status != "paused":
                raise HTTPException(status_code=400, detail=f"Cannot resume: status={job.status}")
            os.kill(pid, signal.SIGCONT)
            job.status = "running"
    except ProcessLookupError:
        await redis.delete(f"download:pid:{job_id}")
        raise HTTPException(status_code=400, detail="Process no longer exists")
    except PermissionError:
        raise HTTPException(status_code=500, detail="Insufficient permission to signal process")

    await db.commit()
    return {"status": job.status}


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: uuid.UUID,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running", "paused"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel: status={job.status}")

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

    job.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}


def _j(j: DownloadJob) -> dict:
    return {
        "id": str(j.id),
        "url": j.url,
        "source": j.source,
        "status": j.status,
        "progress": j.progress,
        "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }
