"""Trash garbage collection — permanently delete expired soft-deleted galleries."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import Gallery

logger = logging.getLogger(__name__)


async def trash_gc_job(ctx: dict) -> dict:
    """Delete galleries that have been in trash longer than retention period."""
    r = get_redis()

    # Check if trash is enabled
    from routers.settings import _get_toggle
    trash_enabled = await _get_toggle("setting:trash_enabled", True)

    if not trash_enabled:
        # Trash disabled: hard-delete ALL soft-deleted galleries
        async with AsyncSessionLocal() as session:
            all_trashed = (await session.execute(
                select(Gallery).where(Gallery.deleted_at.is_not(None))
            )).scalars().all()
            if not all_trashed:
                return {"status": "ok", "deleted": 0, "trash_disabled": True}
            from routers.library import _hard_delete_galleries
            result = await _hard_delete_galleries(session, all_trashed)
        logger.info("[trash_gc] Trash disabled — purged %d galleries", result.get("affected", 0))
        return {"status": "ok", "trash_disabled": True, **result}

    retention_raw = await r.get("setting:trash_retention_days")
    retention_days = int(retention_raw) if retention_raw else 30

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    async with AsyncSessionLocal() as session:
        galleries = (await session.execute(
            select(Gallery).where(
                Gallery.deleted_at.is_not(None),
                Gallery.deleted_at < cutoff,
            )
        )).scalars().all()

        if not galleries:
            return {"status": "ok", "deleted": 0}

        from routers.library import _hard_delete_galleries
        result = await _hard_delete_galleries(session, galleries)

    logger.info("[trash_gc] Permanently deleted %d expired galleries", result.get("affected", 0))
    from core.events import EventType, emit_safe
    await emit_safe(EventType.TRASH_CLEANED, resource_type="system", deleted=result.get("affected", 0))
    return {"status": "ok", **result}
