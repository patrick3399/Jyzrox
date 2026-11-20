"""System reconciliation and event endpoints."""

import json
import logging

from fastapi import APIRouter, Depends, Query, Request

import core.queue
from core.auth import require_auth, require_role
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")


# ── Reconciliation ────────────────────────────────────────────────────


@router.post("/reconcile")
async def trigger_reconcile(
    request: Request,
    _: dict = Depends(_admin),
):
    """Manually trigger the reconciliation job."""
    await core.queue.enqueue("reconciliation_job")
    return {"status": "enqueued"}


@router.get("/reconcile")
async def get_reconcile_status(_: dict = Depends(require_auth)):
    """Get the result of the last reconciliation run."""
    r = get_redis()
    result = await r.get("reconcile:last_result")
    if not result:
        return {"status": "never_run"}
    return json.loads(result)


@router.get("/events")
async def get_recent_events(
    limit: int = Query(50, ge=1, le=200),
    _: dict = Depends(_admin),
):
    """Return recent system events from the EventBus. Admin only."""
    from core.events import event_bus

    events = await event_bus.get_recent(limit)
    return {"events": events, "count": len(events)}
