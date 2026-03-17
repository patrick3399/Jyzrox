"""Application log viewer endpoints (admin only)."""

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.auth import require_role
from core.events import EventType, emit_safe
from core.log_handler import read_log_level, set_log_level
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["logs"])

_admin = require_role("admin")


# ── Request models ────────────────────────────────────────────────────


class LogLevelPatch(BaseModel):
    source: Literal["api", "worker"]
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogRetentionPatch(BaseModel):
    max_entries: int = Field(ge=1000, le=50000)


# ── Helpers ───────────────────────────────────────────────────────────


async def _get_int_setting(redis_key: str, default: int) -> int:
    val = await get_redis().get(redis_key)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return default


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/levels")
async def get_log_levels(_: dict = Depends(_admin)):
    """Return current log level for each source (api, worker)."""
    return {
        "levels": {
            "api": await read_log_level("api"),
            "worker": await read_log_level("worker"),
        }
    }


@router.patch("/levels")
async def patch_log_level(req: LogLevelPatch, auth: dict = Depends(_admin)):
    """Update log level for a source and emit an audit event."""
    await set_log_level(req.source, req.level)

    # For the API process, apply immediately without waiting for pub/sub round-trip
    if req.source == "api":
        logging.getLogger().setLevel(req.level)

    await emit_safe(
        EventType.LOG_LEVEL_CHANGED,
        actor_user_id=auth["user_id"],
        resource_type="log_level",
        source=req.source,
        level=req.level,
    )
    return {"source": req.source, "level": req.level}


@router.get("/")
async def get_logs(
    level: list[str] = Query(default=[]),
    source: list[str] = Query(default=[]),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(_admin),
):
    """Return filtered log entries from Redis with pagination."""
    r = get_redis()

    max_entries = await _get_int_setting("setting:log_max_entries", 2000)
    raw_list = await r.lrange("system_logs", 0, max_entries - 1)

    # Normalise filter sets
    level_filter = {lv.upper() for lv in level if lv}
    source_filter = {s.lower() for s in source if s}
    search_lower = search.lower() if search else None

    entries = []
    for raw in raw_list:
        try:
            entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, TypeError):
            continue

        if level_filter and entry.get("level", "").upper() not in level_filter:
            continue
        if source_filter and entry.get("source", "").lower() not in source_filter:
            continue
        if search_lower:
            msg = entry.get("message", "").lower()
            log_name = entry.get("logger", "").lower()
            if search_lower not in msg and search_lower not in log_name:
                continue

        entries.append(entry)

    total = len(entries)
    page = entries[offset: offset + limit]
    return {
        "logs": page,
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.delete("/")
async def clear_logs(_: dict = Depends(_admin)):
    """Delete all entries from the system_logs list."""
    r = get_redis()
    deleted = await r.llen("system_logs")
    await r.delete("system_logs")
    return {"status": "ok", "deleted": deleted}


@router.get("/retention")
async def get_retention(_: dict = Depends(_admin)):
    """Return current log retention settings."""
    return {
        "max_entries": await _get_int_setting("setting:log_max_entries", 2000),
    }


@router.patch("/retention")
async def patch_retention(req: LogRetentionPatch, _: dict = Depends(_admin)):
    """Update log retention settings."""
    r = get_redis()
    await r.set("setting:log_max_entries", str(req.max_entries))
    return {
        "max_entries": await _get_int_setting("setting:log_max_entries", 2000),
    }
