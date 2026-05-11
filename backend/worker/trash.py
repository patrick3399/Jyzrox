"""Trash garbage collection — permanently delete expired soft-deleted galleries."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import Gallery
from services.gallery_lifecycle import hard_delete_galleries
from services.settings_store import get_int_setting, get_toggle

logger = logging.getLogger(__name__)


async def trash_gc_job(ctx: dict) -> dict:
    """Delete galleries that have been in trash longer than retention period."""
    trash_enabled = await get_toggle("setting:trash_enabled", True)

    if not trash_enabled:
        async with AsyncSessionLocal() as session:
            all_trashed = (
                (await session.execute(select(Gallery).where(Gallery.deleted_at.is_not(None)))).scalars().all()
            )
            if not all_trashed:
                return {"status": "ok", "deleted": 0, "trash_disabled": True}
            result = await hard_delete_galleries(session, all_trashed)
        logger.info("[trash_gc] Trash disabled — purged %d galleries", result.get("affected", 0))
        return {"status": "ok", "trash_disabled": True, **result}

    retention_days = await get_int_setting("setting:trash_retention_days", 30)

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    async with AsyncSessionLocal() as session:
        galleries = (
            (
                await session.execute(
                    select(Gallery).where(
                        Gallery.deleted_at.is_not(None),
                        Gallery.deleted_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )

        if not galleries:
            return {"status": "ok", "deleted": 0}

        result = await hard_delete_galleries(session, galleries)

    logger.info("[trash_gc] Permanently deleted %d expired galleries", result.get("affected", 0))
    await emit_safe(EventType.TRASH_CLEANED, resource_type="system", deleted=result.get("affected", 0))
    return {"status": "ok", **result}
