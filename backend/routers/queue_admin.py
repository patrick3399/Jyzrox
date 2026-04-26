"""Queue administration endpoints — SAQ job and worker monitoring."""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from saq.job import TERMINAL_STATUSES, Status

from core.auth import require_role
import core.queue
from core.queue_config import ALL_QUEUES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["queue admin"])
_admin = require_role("admin")


def _serialize_job(job) -> dict:
    """Convert SAQ Job to JSON-serializable dict."""
    raw_status = job.status.value if isinstance(job.status, Status) else job.status

    # SAQ stores cron jobs with status="queued" even when they are future-scheduled.
    # Derive a "scheduled" display status for jobs whose scheduled time is in the future.
    if raw_status == "queued" and job.scheduled and job.scheduled > time.time():
        display_status = "scheduled"
    else:
        display_status = raw_status

    is_cron = bool(job.key and job.key.startswith("cron:"))

    return {
        "key": job.key,
        "function": job.function,
        "status": display_status,
        "is_cron": is_cron,
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


async def _find_job(job_key: str) -> tuple[Any, Any]:
    """Search all queues for a job by key. Returns (queue, job) or (None, None)."""
    for name in ALL_QUEUES:
        try:
            q = core.queue.get_queue(name)
        except (RuntimeError, KeyError):
            continue
        job = await q.job(job_key)
        if job is not None:
            return q, job
    return None, None


@router.get("/")
async def queue_overview(_: dict = Depends(_admin)):
    """Return aggregated overview across all queues, plus per-queue breakdown."""
    queues = core.queue.get_all_queues()
    infos = await asyncio.gather(*[q.info(jobs=False) for q in queues.values()])

    total_queued = total_active = total_scheduled = 0
    per_queue = []
    all_workers: dict = {}

    for name, info in zip(queues.keys(), infos):
        total_queued    += info.get("queued", 0)
        total_active    += info.get("active", 0)
        total_scheduled += info.get("scheduled", 0)
        all_workers.update(info.get("workers") or {})
        per_queue.append({
            "name": name,
            "queued":    info.get("queued", 0),
            "active":    info.get("active", 0),
            "scheduled": info.get("scheduled", 0),
        })

    workers = [
        {"id": wid, "stats": winfo.get("stats") or {}}
        for wid, winfo in all_workers.items()
    ]
    return {
        "name": "all",
        "queued":    total_queued,
        "active":    total_active,
        "scheduled": total_scheduled,
        "workers":   workers,
        "queues":    per_queue,
    }


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    function_name: str | None = Query(None, alias="function"),
    queue: str | None = Query(None),
    offset: int = 0,
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(_admin),
):
    """List jobs. Optional ?queue= limits to one queue; default searches all."""
    if queue is not None:
        try:
            queues_to_search = {queue: core.queue.get_queue(queue)}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Queue '{queue}' not found")
    else:
        queues_to_search = core.queue.get_all_queues()

    # Fast path: single queue, no filters
    if queue is not None and status is None and function_name is None:
        q = queues_to_search[queue]
        info = await q.info(jobs=True, offset=offset, limit=limit)
        raw_jobs = info.get("jobs") or []
        serialized = []
        for job_dict in raw_jobs:
            job_obj = q.deserialize(job_dict)
            if job_obj is not None:
                serialized.append(_serialize_job(job_obj))
        return {"jobs": serialized, "total": len(serialized)}

    # Full scan path — iterate all relevant queues
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
    matched: list[dict] = []
    for q in queues_to_search.values():
        async for job in q.iter_jobs(statuses=statuses):
            if function_name is not None and job.function != function_name:
                continue
            matched.append(_serialize_job(job))

    total = len(matched)
    return {"jobs": matched[offset: offset + limit], "total": total}


@router.get("/jobs/{job_key}")
async def job_detail(job_key: str, _: dict = Depends(_admin)):
    """Return full details for a single job (searches across all queues)."""
    _q, job = await _find_job(job_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' not found")
    return _serialize_job(job)


@router.post("/jobs/{job_key}/retry")
async def retry_job(job_key: str, _: dict = Depends(_admin)):
    """Re-enqueue a terminal (completed/failed/aborted) job."""
    _q, job = await _find_job(job_key)
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
    """Abort an active or queued job (searches across all queues)."""
    _q, job = await _find_job(job_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_key}' not found")

    if job.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_key}' is already in a terminal state (current status: {job.status.value}) and cannot be aborted.",
        )

    await job.abort("aborted by admin")
    return {"status": "aborted"}
