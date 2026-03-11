"""Dedup Tier 3 — OpenCV pixel-diff verify worker."""

import asyncio
import logging

from sqlalchemy import select, update

from core.database import async_session
from core.redis_client import get_redis
from db.models import Blob, BlobRelationship
from services.cas import resolve_blob_path
from worker.dedup_helpers import _classify_pair, _now_iso, _opencv_pixel_diff

logger = logging.getLogger("worker.dedup_tier3")


async def dedup_tier3_job(ctx: dict) -> dict:
    """Pixel-level validation of needs_t3 pairs using OpenCV.

    Reads pairs with relationship='needs_t3' and moves them to:
    - 'quality_conflict' / 'variant'  if similarity >= threshold (confirmed duplicate)
    - 'resolved'                      if similarity < threshold (false positive, dismiss)
    """
    r = get_redis()

    enabled = await r.get("setting:dedup_opencv_enabled")
    if not enabled or enabled == b"0":
        logger.info("OpenCV disabled — skip")
        return {"status": "skipped", "reason": "disabled"}

    threshold_raw = await r.get("setting:dedup_opencv_threshold")
    threshold = float(threshold_raw) if threshold_raw else 0.85

    total_processed = 0

    while True:
        async with async_session() as session:
            result = await session.execute(
                select(BlobRelationship)
                .where(BlobRelationship.relationship == "needs_t3")
                .order_by(BlobRelationship.id)
                .limit(50)
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
                        .values(relationship="resolved", tier=3)
                    )
                    await session.commit()
                    continue

                path_a = str(resolve_blob_path(blob_a))
                path_b = str(resolve_blob_path(blob_b))

                try:
                    score, diff_type = await asyncio.to_thread(_opencv_pixel_diff, path_a, path_b)
                except Exception as exc:
                    logger.warning("OpenCV failed for pair %d: %s", pair.id, exc)
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(relationship="quality_conflict", tier=3)
                    )
                    await session.commit()
                    continue

                if score >= threshold:
                    # Confirmed similar — re-classify with heuristics and send to review
                    heuristic_raw = await r.get("setting:dedup_heuristic_enabled")
                    heuristic_enabled = heuristic_raw == b"1"
                    rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled)
                    final_keep = pair.suggested_keep or keep
                    final_reason = pair.reason or reason
                else:
                    # False positive — dismiss
                    rel = "resolved"
                    final_keep = pair.suggested_keep
                    final_reason = pair.reason

                await session.execute(
                    update(BlobRelationship)
                    .where(BlobRelationship.id == pair.id)
                    .values(
                        relationship=rel,
                        suggested_keep=final_keep,
                        reason=final_reason,
                        diff_score=score,
                        diff_type=diff_type,
                        tier=3,
                    )
                )
                await session.commit()
                total_processed += 1

    await r.set("cron:dedup_tier3:last_run", _now_iso())
    await r.set("cron:dedup_tier3:last_status", f"processed={total_processed}")
    logger.info("Done, processed: %d", total_processed)
    return {"status": "ok", "processed": total_processed}
