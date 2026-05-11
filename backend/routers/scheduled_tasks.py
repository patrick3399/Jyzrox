"""Scheduled tasks management endpoints (Immich-style cron UI)."""

import logging
import uuid
from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import core.queue
from core.auth import require_role
from core.redis_client import get_redis
from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scheduled-tasks"])

_admin = require_role("admin")


class PatchTaskRequest(BaseModel):
    enabled: bool | None = None
    cron_expr: str | None = None


def _decode_redis(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


def _next_run(cron_expr: str, enabled: bool, last_run: str | None) -> str | None:
    if not enabled:
        return None
    try:
        base = datetime.fromisoformat(last_run) if last_run else datetime.now(UTC)
        return croniter(cron_expr, base).get_next(datetime).isoformat()
    except ValueError, KeyError:
        return None


@router.get("/")
async def list_scheduled_tasks(
    _: dict = Depends(_admin),
):
    """List all scheduled tasks with their config and status."""
    r = get_redis()
    tasks = []
    for task_id, defn in CONFIGURABLE_TASK_DEFS.items():
        enabled_raw = await r.get(f"cron:{task_id}:enabled")
        cron_expr_raw = await r.get(f"cron:{task_id}:cron_expr")
        last_run_raw = await r.get(f"cron:{task_id}:last_run")
        last_status_raw = await r.get(f"cron:{task_id}:last_status")
        last_error_raw = await r.get(f"cron:{task_id}:last_error")

        enabled = _decode_redis(enabled_raw) != "0" if enabled_raw else defn.default_enabled
        cron_expr = _decode_redis(cron_expr_raw) or defn.default_cron
        last_run = _decode_redis(last_run_raw)
        last_status = _decode_redis(last_status_raw)
        if last_status == "running":
            claim_exists = await r.exists(f"cron:{task_id}:claim", f"cron:{task_id}:manual_claim")
            progress_exists = await r.exists(defn.progress_key) if defn.progress_key else 0
            if not claim_exists and not progress_exists:
                last_status = "stale"

        tasks.append(
            {
                "id": task_id,
                "name": defn.name,
                "description": defn.description,
                "enabled": enabled,
                "cron_expr": cron_expr,
                "default_cron": defn.default_cron,
                "next_run": _next_run(cron_expr, enabled, last_run),
                "last_run": last_run,
                "last_status": last_status,
                "last_error": _decode_redis(last_error_raw),
            }
        )

    return {"tasks": tasks}


@router.patch("/{task_id}")
async def update_scheduled_task(
    task_id: str,
    body: PatchTaskRequest,
    _: dict = Depends(_admin),
):
    """Update a scheduled task's config (enabled, cron_expr)."""
    if task_id not in CONFIGURABLE_TASK_DEFS:
        raise HTTPException(status_code=404, detail="Task not found")

    r = get_redis()

    if body.enabled is not None:
        await r.set(f"cron:{task_id}:enabled", "1" if body.enabled else "0")

    if body.cron_expr is not None:
        try:
            croniter(body.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")
        await r.set(f"cron:{task_id}:cron_expr", body.cron_expr)

    return {"status": "ok", "task_id": task_id}


@router.post("/{task_id}/run")
async def run_scheduled_task(
    task_id: str,
    _: dict = Depends(_admin),
):
    """Manually trigger a scheduled task."""
    if task_id not in CONFIGURABLE_TASK_DEFS:
        raise HTTPException(status_code=404, detail="Task not found")

    defn = CONFIGURABLE_TASK_DEFS[task_id]
    job_name = defn.job_name
    r = get_redis()
    claim_key = f"cron:{task_id}:manual_claim"
    claimed = await r.set(claim_key, "1", nx=True, ex=300)
    if not claimed:
        return {"status": "already_queued", "task_id": task_id, "job": job_name}

    try:
        await core.queue.enqueue(
            job_name,
            **defn.manual_kwargs,
            _timeout=defn.manual_timeout,
            _job_id=f"manual:{task_id}:{uuid.uuid4().hex[:8]}",
        )
    except Exception as exc:
        await r.delete(claim_key)
        logger.error("Failed to enqueue %s: %s", job_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "task_id": task_id, "job": job_name}
