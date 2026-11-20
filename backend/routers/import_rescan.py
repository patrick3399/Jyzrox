"""Library rescan endpoints and legacy scan-settings compatibility."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import core.queue
from core.auth import require_role
from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import Gallery, LibraryPath

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


# NOTE: /rescan/status is defined BEFORE /rescan/{gallery_id} so FastAPI does
# not attempt to coerce the literal string "status" into an integer gallery_id.
@router.get("/rescan/status")
async def rescan_status(_: dict = Depends(_member)):
    """Return current rescan progress stored in Redis."""
    r = get_redis()
    data = await r.get("rescan:progress")
    if not data:
        return {"running": False}
    parsed = json.loads(data)
    is_running = parsed.get("status") == "running"
    return {"running": is_running, **parsed}


@router.post("/rescan")
async def rescan_library(request: Request, _: dict = Depends(_admin)):
    """Enqueue a full library rescan job."""
    await core.queue.enqueue("auto_discover_job", _timeout=3600)
    await core.queue.enqueue("rescan_library_job", _timeout=7200)
    return {"status": "enqueued"}


@router.post("/rescan/cancel")
async def cancel_rescan(_: dict = Depends(_admin)):
    """Signal the running rescan to stop at the next gallery boundary."""
    r = get_redis()
    await r.set("rescan:cancel", "1", ex=300)  # expires in 5 min as safety net
    return {"status": "cancelling"}


@router.post("/rescan/path/{library_id}")
async def rescan_library_path(library_id: int, request: Request, _: dict = Depends(_admin)):
    """Enqueue rescan for all galleries under a specific library path.

    NOTE: defined BEFORE /rescan/{gallery_id} so FastAPI does not attempt to
    coerce the literal string "path" into an integer gallery_id.
    """
    async with async_session() as session:
        lp = await session.get(LibraryPath, library_id)
        if not lp:
            raise HTTPException(404, "Library path not found")
    await core.queue.enqueue("rescan_library_path_job", library_path=lp.path, _timeout=3600)
    return {"status": "enqueued", "path": lp.path}


@router.post("/rescan/{gallery_id}")
async def rescan_gallery(
    gallery_id: int,
    request: Request,
    auth: dict = Depends(_member),
):
    """Enqueue a rescan job for a single gallery."""
    async with async_session() as session:
        gallery = await session.get(Gallery, gallery_id)
        if not gallery:
            raise HTTPException(404, "Gallery not found")
        if (
            auth["role"] != "admin"
            and gallery.created_by_user_id is not None
            and gallery.created_by_user_id != auth["user_id"]
        ):
            raise HTTPException(403, "Not your gallery")
    await core.queue.enqueue("rescan_gallery_job", gallery_id=gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}


#
# New UI controls external folder scans through /api/scheduled-tasks and
# cron:library_scan:* Redis keys. Keep these endpoints for older clients only;
# do not wire them back into scheduled library_scan behavior.


class ScanScheduleRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = None


@router.get("/scan-settings")
async def get_scan_settings(_: dict = Depends(_member)):
    """Return current scan schedule settings."""
    r = get_redis()
    enabled = await r.get("scan:schedule:enabled")
    interval = await r.get("scan:schedule:interval_hours")
    last_run = await r.get("scan:schedule:last_run")
    return {
        "enabled": enabled != b"0" if enabled is not None else True,
        "interval_hours": int(interval) if interval else settings.library_scan_interval_hours,
        "last_run": last_run.decode() if last_run else None,
    }


@router.patch("/scan-settings")
async def update_scan_settings(req: ScanScheduleRequest, _: dict = Depends(_admin)):
    """Update scan schedule settings (stored in Redis)."""
    r = get_redis()
    if req.enabled is not None:
        await r.set("scan:schedule:enabled", "1" if req.enabled else "0")
    if req.interval_hours is not None:
        if req.interval_hours < 6 or req.interval_hours > 168:
            raise HTTPException(400, "Interval must be between 6 and 168 hours")
        await r.set("scan:schedule:interval_hours", str(req.interval_hours))

    # Return updated settings
    return await get_scan_settings(_)
