"""Trash garbage collection — permanently delete expired soft-deleted galleries."""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from core.redis_client import get_redis
from db.models import Gallery
from services.gallery_lifecycle import hard_delete_in_chunks, trash_scope
from services.settings_store import get_int_setting, get_toggle

logger = logging.getLogger(__name__)


PURGE_GUARD_TTL = 300


def purge_guard_key(user_id: int) -> str:
    return f"trash:purge:{user_id}"


async def trash_gc_job(ctx: dict) -> dict:
    """Delete galleries that have been in trash longer than retention period."""
    trash_enabled = await get_toggle("setting:trash_enabled", True)

    if not trash_enabled:
        async with AsyncSessionLocal() as session:
            ids = list((await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_not(None)))).scalars())
        if not ids:
            return {"status": "ok", "deleted": 0, "trash_disabled": True}
        result = await hard_delete_in_chunks(AsyncSessionLocal, ids)
        logger.info("[trash_gc] Trash disabled — purged %d galleries", result.get("affected", 0))
        return {"status": "ok", "trash_disabled": True, **result}

    retention_days = await get_int_setting("setting:trash_retention_days", 30)
    if retention_days < 1:
        # Edge case #93: zero/negative retention would delete all trashed galleries immediately.
        logger.warning("[trash_gc] retention_days=%d invalid (must be >= 1), defaulting to 30", retention_days)
        retention_days = 30

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    async with AsyncSessionLocal() as session:
        ids = list(
            (
                await session.execute(
                    select(Gallery.id).where(
                        Gallery.deleted_at.is_not(None),
                        Gallery.deleted_at < cutoff,
                    )
                )
            ).scalars()
        )

    if not ids:
        return {"status": "ok", "deleted": 0}

    result = await hard_delete_in_chunks(AsyncSessionLocal, ids)

    logger.info("[trash_gc] Permanently deleted %d expired galleries", result.get("affected", 0))
    await emit_safe(EventType.TRASH_CLEANED, resource_type="system", deleted=result.get("affected", 0))
    return {"status": "ok", **result}


async def trash_purge_job(ctx: dict, *, user_id: int, role: str, gallery_ids: list[int]) -> dict:
    """Permanently delete a snapshot of trashed galleries for one user, chunk by chunk.

    Only ids that are still trashed and still inside the user's trash scope are
    deleted. The Redis guard (``trash:purge:{user_id}``) is refreshed per chunk
    and always released in ``finally``.
    """
    key = purge_guard_key(user_id)
    total = len(set(gallery_ids))

    async def _on_chunk(done: int, total_: int) -> None:
        try:
            await get_redis().set(key, json.dumps({"done": done, "total": total_}), ex=PURGE_GUARD_TTL)
        except Exception:
            logger.warning("[trash_purge] guard refresh failed", exc_info=True)
        await emit_safe(
            EventType.TRASH_PURGE_PROGRESS,
            actor_user_id=user_id,
            resource_type="gallery",
            done=done,
            total=total_,
        )

    try:
        result = await hard_delete_in_chunks(
            AsyncSessionLocal,
            gallery_ids,
            scope=trash_scope({"user_id": user_id, "role": role}),
            on_chunk=_on_chunk,
        )
        affected = result.get("affected", 0)
        logger.info(
            "[trash_purge] user=%s deleted %d/%d galleries (failed_chunks=%d)",
            user_id,
            affected,
            total,
            result.get("failed_chunks", 0),
        )
        await emit_safe(
            EventType.TRASH_CLEANED,
            actor_user_id=user_id,
            resource_type="gallery",
            deleted=affected,
            total=total,
        )
        return {"status": "ok", **result}
    finally:
        try:
            await get_redis().delete(key)
        except Exception:
            logger.warning("[trash_purge] guard release failed", exc_info=True)
