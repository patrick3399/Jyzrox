"""Backfill thumbhash for existing blobs that don't have one yet."""

import asyncio
import base64
import logging

from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Blob
from services.cas import thumb_dir

logger = logging.getLogger(__name__)


def _generate_thumbhash(thumb_path) -> str | None:
    """Synchronous thumbhash generation from a thumbnail file.

    Runs in a thread pool via asyncio.to_thread to avoid blocking the event loop.
    """
    import thumbhash as _thumbhash
    from PIL import Image as PILImage

    with PILImage.open(thumb_path) as pil:
        pil.thumbnail((100, 100))
        rgba = pil.convert("RGBA")
        w, h = rgba.size
        rgba_data = rgba.tobytes()
        hash_bytes = _thumbhash.rgba_to_thumbhash(w, h, rgba_data)
        return base64.b64encode(hash_bytes).decode()


async def thumbhash_backfill_job(ctx: dict, batch_size: int = 500) -> dict:
    """Batch-process blobs missing thumbhash, using existing thumb_160.webp."""
    processed = 0
    failed = 0
    last_sha = None

    while True:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Blob)
                .where(Blob.thumbhash.is_(None))
                .order_by(Blob.sha256)
                .limit(batch_size)
            )
            if last_sha:
                stmt = stmt.where(Blob.sha256 > last_sha)

            blobs = (await session.execute(stmt)).scalars().all()
            if not blobs:
                break

            for blob in blobs:
                last_sha = blob.sha256
                td = thumb_dir(blob.sha256)
                thumb_path = td / "thumb_160.webp"

                if not thumb_path.exists():
                    continue

                try:
                    result = await asyncio.to_thread(_generate_thumbhash, thumb_path)
                    if result:
                        blob.thumbhash = result
                        processed += 1
                except Exception as exc:
                    logger.warning("[thumbhash_backfill] %s: %s", blob.sha256[:12], exc)
                    failed += 1

            await session.commit()

        logger.info("[thumbhash_backfill] processed=%d failed=%d last=%s", processed, failed, last_sha[:12] if last_sha else "")

    logger.info("[thumbhash_backfill] done: processed=%d failed=%d", processed, failed)
    return {"status": "done", "processed": processed, "failed": failed}
