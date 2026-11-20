"""Dedup scan control API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import core.queue
from core.auth import require_role

router = APIRouter()

_admin = require_role("admin")


class ScanStartRequest(BaseModel):
    mode: str  # "reset" or "pending"


class ScanSignalRequest(BaseModel):
    signal: str  # "pause", "resume", or "stop"


@router.get("/scan/progress")
async def get_scan_progress(_: dict = Depends(_admin)):
    """Return current dedup scan progress."""
    from core.redis_client import get_redis

    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw is None:
        last_status = await r.get("dedup:progress:last_status")
        last_started = await r.get("dedup:progress:last_started")
        last_finished = await r.get("dedup:progress:last_finished")
        last_error = await r.get("dedup:progress:last_error")

        def _decode(value):
            return value.decode() if isinstance(value, bytes) else value

        return {
            "status": "idle",
            "last_status": _decode(last_status),
            "last_started": _decode(last_started),
            "last_finished": _decode(last_finished),
            "last_error": _decode(last_error),
        }

    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw

    current_raw = await r.get("dedup:progress:current")
    total_raw = await r.get("dedup:progress:total")
    tier_raw = await r.get("dedup:progress:tier")
    mode_raw = await r.get("dedup:progress:mode")

    current = int(current_raw) if current_raw else 0
    total = int(total_raw) if total_raw else 0
    tier = int(tier_raw) if tier_raw else 1
    mode = (mode_raw.decode() if isinstance(mode_raw, bytes) else mode_raw) or "pending"

    percent = round(current / total * 100) if total > 0 else 0

    return {
        "status": status,
        "current": current,
        "total": total,
        "tier": tier,
        "mode": mode,
        "percent": percent,
    }


@router.post("/scan/start")
async def start_scan(
    req: ScanStartRequest,
    _: dict = Depends(_admin),
):
    """Enqueue a dedup scan job. 409 if already running/paused."""
    from core.redis_client import get_redis

    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw in (b"running", b"paused", "running", "paused"):
        raise HTTPException(status_code=409, detail="Scan already running")

    if req.mode not in ("reset", "pending"):
        raise HTTPException(status_code=422, detail="mode must be 'reset' or 'pending'")

    await core.queue.enqueue("dedup_scan_job", _job_id="dedup_scan:singleton", mode=req.mode)
    from core.events import EventType, emit_safe

    await emit_safe(EventType.DEDUP_SCAN_STARTED, actor_user_id=_["user_id"], resource_type="system")
    return {"status": "queued"}


@router.post("/scan/signal")
async def send_scan_signal(
    req: ScanSignalRequest,
    _: dict = Depends(_admin),
):
    """Send a pause/resume/stop signal to the running scan. 409 if idle."""
    from core.redis_client import get_redis

    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw is None:
        raise HTTPException(status_code=409, detail="No scan running")

    if req.signal not in ("pause", "resume", "stop"):
        raise HTTPException(status_code=422, detail="signal must be 'pause', 'resume', or 'stop'")

    await r.set("dedup:progress:signal", req.signal)
    return {"status": "ok"}
