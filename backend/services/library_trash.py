"""Library split from routers/library.py (library_trash)."""

import json
import logging
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

import core.queue
from core.redis_client import get_redis
from db.models import (
    Gallery,
)
from services.explorer_query import ExplorerQuerySpec, build_explorer_gallery_query
from services.library_serializers import serialize_gallery as _g

logger = logging.getLogger(__name__)


def trash_item(g: Gallery, cover_thumb: str | None, users: dict[int, str], merged: dict[int, Gallery]) -> dict:
    """Serialize a trashed gallery with why/who/into-what it was trashed."""
    data = _g(g, cover_thumb=cover_thumb)
    data["deleted_at"] = g.deleted_at.isoformat() if g.deleted_at else None
    data["deleted_reason"] = g.deleted_reason
    uid = g.deleted_by_user_id
    data["deleted_by"] = {"id": uid, "username": users[uid]} if uid is not None and uid in users else None
    target = merged.get(g.merged_into_gallery_id) if g.merged_into_gallery_id is not None else None
    data["merged_into"] = (
        {"source": target.source, "source_id": target.source_id, "title": target.title} if target else None
    )
    return data


TrashSort = Literal["deleted_at", "title", "pages", "size"]


TrashDirection = Literal["asc", "desc"]


TrashReasonFilter = Literal["user", "merged", "source_missing", "unknown"]


def trash_query(
    auth: dict,
    q: str | None = None,
    source: str | None = None,
    reason: str | None = None,
    sort: str = "deleted_at",
    direction: str = "desc",
):
    """Filtered/sorted select of trashed galleries in the caller's trash scope."""
    stmt = build_explorer_gallery_query(
        ExplorerQuerySpec(node_kind="trash", query=q or "", sort=sort, direction=direction), auth
    )
    if source:
        stmt = stmt.where(Gallery.source == source)
    if reason == "unknown":
        stmt = stmt.where(Gallery.deleted_reason.is_(None))
    elif reason:
        stmt = stmt.where(Gallery.deleted_reason == reason)
    return stmt


def purge_guard_key(user_id: int) -> str:
    return f"trash:purge:{user_id}"


async def queue_purge(auth: dict, ids: list[int]) -> JSONResponse:
    """Take the per-user purge guard and enqueue ``trash_purge_job`` for ``ids``."""
    if not ids:
        return JSONResponse({"status": "ok", "total": 0}, status_code=200)
    key = _purge_guard_key(auth["user_id"])
    try:
        acquired = await get_redis().set(key, json.dumps({"done": 0, "total": len(ids)}), nx=True, ex=300)
    except RedisError, RuntimeError:
        logger.error("Trash purge guard unavailable", exc_info=True)
        raise HTTPException(status_code=503, detail="Purge service unavailable")
    if not acquired:
        raise HTTPException(status_code=409, detail="A purge is already running")
    try:
        # No _job_id: completed SAQ jobs keep their key for a TTL and would dedupe a later purge.
        await core.queue.enqueue("trash_purge_job", user_id=auth["user_id"], role=auth["role"], gallery_ids=ids)
    except Exception:
        logger.error("Failed to enqueue trash_purge_job", exc_info=True)
        try:
            await get_redis().delete(key)
        except RedisError:
            logger.warning("Could not release purge guard after enqueue failure", exc_info=True)
        raise HTTPException(status_code=503, detail="Could not queue purge")
    return JSONResponse({"status": "queued", "total": len(ids)}, status_code=202)


_purge_guard_key = purge_guard_key
