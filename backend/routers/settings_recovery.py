"""Settings: worker recovery strategy."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import require_role
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


class RecoveryStrategyUpdate(BaseModel):
    running: Literal["auto_retry", "mark_failed"] | None = None
    paused: Literal["keep_paused", "auto_retry", "mark_failed"] | None = None


@router.get("/recovery-strategy")
async def get_recovery_strategy(_: dict = Depends(_admin)):
    """Get worker recovery strategy settings."""
    redis = get_redis()
    running = ((await redis.get("setting:recovery_running")) or b"auto_retry").decode()
    paused = ((await redis.get("setting:recovery_paused")) or b"keep_paused").decode()
    return {"running": running, "paused": paused}


@router.patch("/recovery-strategy")
async def patch_recovery_strategy(req: RecoveryStrategyUpdate, _: dict = Depends(_admin)):
    """Update worker recovery strategy settings."""
    redis = get_redis()
    if req.running is not None:
        await redis.set("setting:recovery_running", req.running)
    if req.paused is not None:
        await redis.set("setting:recovery_paused", req.paused)
    running = (
        req.running
        if req.running is not None
        else ((await redis.get("setting:recovery_running")) or b"auto_retry").decode()
    )
    paused = (
        req.paused
        if req.paused is not None
        else ((await redis.get("setting:recovery_paused")) or b"keep_paused").decode()
    )
    return {"running": running, "paused": paused}
