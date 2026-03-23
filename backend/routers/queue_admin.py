"""Queue administration endpoints — SAQ job and worker monitoring."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from saq.job import TERMINAL_STATUSES, Status

from core.auth import require_role
import core.queue

logger = logging.getLogger(__name__)
router = APIRouter(tags=["queue admin"])
_admin = require_role("admin")


def _serialize_job(job) -> dict:
    """Convert SAQ Job to JSON-serializable dict."""
    return {
        "key": job.key,
        "function": job.function,
        "status": job.status.value if isinstance(job.status, Status) else job.status,
        "kwargs": job.kwargs or {},
        "result": repr(job.result) if job.result is not None else None,
        "error": job.error,
        "queued": int(job.queued) if job.queued else None,
        "started": int(job.started) if job.started else None,
        "completed": int(job.completed) if job.completed else None,
        "progress": job.progress or 0,
        "attempts": job.attempts or 0,
        "meta": job.meta or {},
    }


@router.get("/")
async def queue_overview(_: dict = Depends(_admin)):
    """Return queue overview: counts and worker list."""
    q = core.queue.get_queue()
    info = await q.info(jobs=False)
    workers = [
        {
            "id": worker_id,
            "stats": worker_info.get("stats") or {},
        }
        for worker_id, worker_info in (info.get("workers") or {}).items()
    ]
    return {
        "name": info["name"],
        "queued": info["queued"],
        "active": info["active"],
        "scheduled": info["scheduled"],
        "workers": workers,
    }


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    function_name: str | None = Query(None, alias="function"),
    offset: int = 0,
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(_admin),
):
    """List jobs with optional filtering by status and function name."""
    q = core.queue.get_queue()

    if status is None and function_name is None:
        # Fast path: use info() which reads from Redis structures directly
        info = await q.info(jobs=True, offset=offset, limit=limit)
        raw_jobs = info.get("jobs") or []
        # info returns list of dicts (to_dict() output), reconstruct Job objects for serialization
        serialized = []
        for job_dict in raw_jobs:
            # Deserialize via queue so the queue reference is set correctly
            job_obj = q.deserialize(job_dict)
            if job_obj is not None:
                serialized.append(_serialize_job(job_obj))
        return {"jobs": serialized, "total": len(serialized)}

    # Filtered path: iterate all jobs and apply filters
    matched: list[dict] = []
    status_filter: Status | None = None
    if status is not None:
        try:
            status_filter = Status(status.lower())
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{status}'. Valid values: {[s.value for s in Status]}",
            )

    statuses = [status_filter] if status_filter else list(Status)
    async for job in q.iter_jobs(statuses=statuses):
        if function_name is not None and job.function != function_name:
            continue
        matched.append(_serialize_job(job))

    total = len(matched)
    return {"jobs": matched[offset : offset + limit], "total": total}


@router.get("/jobs/{job_key}")
async def job_detail(job_key: str, _: dict = Depends(_admin)):
    """Return full details for a single job."""
    q = core.queue.get_queue()
    job = await q.job(job_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' not found")
    return _serialize_job(job)


@router.post("/jobs/{job_key}/retry")
async def retry_job(job_key: str, _: dict = Depends(_admin)):
    """Re-enqueue a terminal (completed/failed/aborted) job."""
    q = core.queue.get_queue()
    job = await q.job(job_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' not found")

    if job.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_key}' is not in a terminal state (current status: {job.status.value}). Only completed, failed, or aborted jobs can be retried.",
        )

    kwargs = job.kwargs or {}
    new_job = await core.queue.enqueue(job.function, **kwargs)
    return {
        "status": "retried",
        "new_key": new_job.key if new_job else None,
    }


@router.post("/jobs/{job_key}/abort")
async def abort_job(job_key: str, _: dict = Depends(_admin)):
    """Abort an active or queued job."""
    q = core.queue.get_queue()
    job = await q.job(job_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' not found")

    # Only abort jobs that are not already in a terminal state
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_key}' is already in a terminal state (current status: {job.status.value}) and cannot be aborted.",
        )

    await job.abort("aborted by admin")
    return {"status": "aborted"}
