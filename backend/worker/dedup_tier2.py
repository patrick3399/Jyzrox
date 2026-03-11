"""Dedup Tier 2 — heuristic classify worker."""

import logging

from sqlalchemy import select, update

from core.database import async_session
from core.redis_client import get_redis
from db.models import Blob, BlobRelationship, Image
from worker.dedup_helpers import _classify_pair, _now_iso

logger = logging.getLogger("worker.dedup_tier2")


async def dedup_tier2_job(ctx: dict) -> dict:
    """Classify needs_t2 pairs using resolution/file-size heuristics.

    Reads pairs with relationship='needs_t2' and moves them to:
    - 'needs_t3'       if OpenCV is enabled (defer to Tier 3 for pixel validation)
    - 'quality_conflict' / 'variant'  otherwise (send directly to review queue)
    """
    r = get_redis()

    enabled = await r.get("setting:dedup_phash_enabled")
    if not enabled or enabled == b"0":
        logger.info("pHash disabled — skip")
        return {"status": "skipped", "reason": "disabled"}

    heuristic_raw = await r.get("setting:dedup_heuristic_enabled")
    heuristic_enabled = heuristic_raw == b"1"

    opencv_raw = await r.get("setting:dedup_opencv_enabled")
    opencv_enabled = opencv_raw == b"1"

    total_processed = 0

    while True:
        async with async_session() as session:
            result = await session.execute(
                select(BlobRelationship)
                .where(BlobRelationship.relationship == "needs_t2")
                .order_by(BlobRelationship.id)
                .limit(200)
            )
            pairs = list(result.scalars())

        if not pairs:
            break

        for pair in pairs:
            async with async_session() as session:
                blob_a_result = await session.execute(select(Blob).where(Blob.sha256 == pair.sha_a))
                blob_a = blob_a_result.scalar_one_or_none()
                blob_b_result = await session.execute(select(Blob).where(Blob.sha256 == pair.sha_b))
                blob_b = blob_b_result.scalar_one_or_none()

                if not blob_a or not blob_b:
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(relationship="resolved", tier=2)
                    )
                    await session.commit()
                    continue

                # Cross-gallery check: blobs appearing in the same gallery are
                # intentional variants (差分) and should be auto-whitelisted.
                same_gal_subq = (
                    select(Image.gallery_id)
                    .where(Image.blob_sha256 == pair.sha_a)
                    .where(
                        Image.gallery_id.in_(
                            select(Image.gallery_id).where(Image.blob_sha256 == pair.sha_b)
                        )
                    )
                    .limit(1)
                    .exists()
                )
                same_gal = (await session.execute(select(same_gal_subq))).scalar()

                if same_gal:
                    logger.info("same_gallery_variant: pair %d", pair.id)
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(relationship="whitelisted", reason="same_gallery_variant", tier=2)
                    )
                    await session.commit()
                    total_processed += 1
                    continue

                rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled)
                next_rel = "needs_t3" if opencv_enabled else rel

                await session.execute(
                    update(BlobRelationship)
                    .where(BlobRelationship.id == pair.id)
                    .values(
                        relationship=next_rel,
                        suggested_keep=keep,
                        reason=reason,
                        tier=2,
                    )
                )
                await session.commit()
                total_processed += 1

    await r.set("cron:dedup_tier2:last_run", _now_iso())
    await r.set("cron:dedup_tier2:last_status", f"processed={total_processed}")
    logger.info("Done, processed: %d", total_processed)
    return {"status": "ok", "processed": total_processed}
