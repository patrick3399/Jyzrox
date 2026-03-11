"""Scheduled tasks management endpoints (Immich-style cron UI)."""

import logging

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import require_auth
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scheduled-tasks"])

TASK_DEFS = {
    "library_scan": {
        "name": "Library Scan",
        "description": "Scan all library paths for new content and verify existing files",
        "default_cron": "0 * * * *",
        "default_enabled": True,
        "job": "scheduled_scan_job",
    },
    "reconciliation": {
        "name": "Reconciliation",
        "description": "Verify database/filesystem consistency and clean orphaned blobs",
        "default_cron": "0 3 * * 1",
        "default_enabled": True,
        "job": "reconciliation_job",
    },
    "check_subscriptions": {
        "name": "Check Subscriptions",
        "description": "Check followed artists and subscriptions for new works",
        "default_cron": "30 */2 * * *",
        "default_enabled": True,
        "job": "check_followed_artists",
    },
    "dedup_tier1": {
        "name": "Dedup — pHash Scan",
        "description": "Scan all images for similar pairs using perceptual hashing",
        "default_cron": "0 8 * * *",
        "default_enabled": False,
        "job": "dedup_tier1_job",
    },
    "dedup_tier2": {
        "name": "Dedup — Heuristic Classify",
        "description": "Classify similar pairs by resolution and file size",
        "default_cron": "0 9 * * *",
        "default_enabled": False,
        "job": "dedup_tier2_job",
    },
    "dedup_tier3": {
        "name": "Dedup — OpenCV Verify",
        "description": "Pixel-level validation of similar pairs (CPU intensive, runs nightly)",
        "default_cron": "0 2 * * *",
        "default_enabled": False,
        "job": "dedup_tier3_job",
    },
}


class PatchTaskRequest(BaseModel):
    enabled: bool | None = None
    cron_expr: str | None = None


@router.get("/")
async def list_scheduled_tasks(
    _: dict = Depends(require_auth),
):
    """List all scheduled tasks with their config and status."""
    r = get_redis()
    tasks = []
    for task_id, defn in TASK_DEFS.items():
        enabled_raw = await r.get(f"cron:{task_id}:enabled")
        cron_expr_raw = await r.get(f"cron:{task_id}:cron_expr")
        last_run_raw = await r.get(f"cron:{task_id}:last_run")
        last_status_raw = await r.get(f"cron:{task_id}:last_status")
        last_error_raw = await r.get(f"cron:{task_id}:last_error")

        tasks.append({
            "id": task_id,
            "name": defn["name"],
            "description": defn["description"],
            "enabled": enabled_raw.decode() != "0" if enabled_raw else defn["default_enabled"],
            "cron_expr": cron_expr_raw.decode() if cron_expr_raw else defn["default_cron"],
            "default_cron": defn["default_cron"],
            "last_run": last_run_raw.decode() if last_run_raw else None,
            "last_status": last_status_raw.decode() if last_status_raw else None,
            "last_error": last_error_raw.decode() if last_error_raw else None,
        })

    return {"tasks": tasks}


@router.patch("/{task_id}")
async def update_scheduled_task(
    task_id: str,
    body: PatchTaskRequest,
    _: dict = Depends(require_auth),
):
    """Update a scheduled task's config (enabled, cron_expr)."""
    if task_id not in TASK_DEFS:
        raise HTTPException(status_code=404, detail="Task not found")

    r = get_redis()

    if body.enabled is not None:
        await r.set(f"cron:{task_id}:enabled", "1" if body.enabled else "0")

    if body.cron_expr is not None:
        from croniter import croniter
        try:
            croniter(body.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")
        await r.set(f"cron:{task_id}:cron_expr", body.cron_expr)

    return {"status": "ok", "task_id": task_id}


@router.post("/{task_id}/run")
async def run_scheduled_task(
    task_id: str,
    request: Request,
    _: dict = Depends(require_auth),
):
    """Manually trigger a scheduled task."""
    if task_id not in TASK_DEFS:
        raise HTTPException(status_code=404, detail="Task not found")

    defn = TASK_DEFS[task_id]
    job_name = defn["job"]

    try:
        arq: ArqRedis = request.app.state.arq
        await arq.enqueue_job(job_name, _job_id=f"manual:{task_id}")
    except Exception as exc:
        logger.error("Failed to enqueue %s: %s", job_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "task_id": task_id, "job": job_name}
