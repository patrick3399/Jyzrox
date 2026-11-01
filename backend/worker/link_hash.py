"""Background hash pass for pending link pages (ADR 0015)."""

from services.link_sync import hash_pending_images, sync_link_gallery
from worker.constants import logger


async def link_hash_job(ctx: dict, gallery_id: int) -> dict:
    """Register anything the folder gained since the last sync, then hash every pending page."""
    await sync_link_gallery(gallery_id, redis=ctx["redis"], force=True)
    result = await hash_pending_images(gallery_id)
    logger.info(
        "[link_hash] gallery_id=%d status=%s hashed=%d failed=%d remaining=%d",
        gallery_id,
        result.status,
        result.hashed,
        result.failed,
        result.remaining,
    )
    return {
        "status": result.status,
        "gallery_id": gallery_id,
        "hashed": result.hashed,
        "failed": result.failed,
        "remaining": result.remaining,
    }
