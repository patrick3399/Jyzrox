"""Dedup Tier 2 — heuristic classify worker."""

import logging

from sqlalchemy import select, update

from core.database import async_session
from core.redis_client import get_redis
from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
from db.models import Blob, BlobRelationship
from worker.dedup_helpers import _classify_pair, _now_iso, _pair_context_scope
from worker.helpers import _cron_record, _cron_should_run

logger = logging.getLogger("worker.dedup_tier2")


async def dedup_tier2_job(ctx: dict, force: bool = False) -> dict:
    """Classify needs_t2 pairs using resolution/file-size heuristics.

    Reads new pairs plus context-suppressed pairs that need re-evaluation.
    Same-gallery-only occurrences remain suppressed without becoming a global
    whitelist. Cross-gallery and mixed-context pairs move to:
    - 'needs_t3'       if OpenCV is enabled (defer to Tier 3 for pixel validation)
    - 'quality_conflict' / 'variant'  otherwise (send directly to review queue)
    """
    defn = CONFIGURABLE_TASK_DEFS["dedup_tier2"]
    if not force and not await _cron_should_run(ctx, defn.task_id, defn.default_cron, defn.default_enabled):
        logger.info("cron gate not reached — skip")
        return {"status": "skipped", "reason": "cron_gate"}
    await _cron_record(ctx, defn.task_id, "running")
    try:
        result = await _classify_pending_pairs()
    except Exception as exc:
        await _cron_record(ctx, defn.task_id, "failed", str(exc))
        raise
    status = result.get("status", "ok")
    await _cron_record(ctx, defn.task_id, "ok" if status == "ok" else result.get("reason", status))
    return result


async def _classify_pending_pairs() -> dict:
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

    last_id = 0
    while True:
        async with async_session() as session:
            result = await session.execute(
                select(BlobRelationship)
                .where(BlobRelationship.relationship.in_(("needs_t2", "same_gallery_only")))
                .where(BlobRelationship.id > last_id)
                .order_by(BlobRelationship.id)
                .limit(200)
            )
            pairs = list(result.scalars())

        if not pairs:
            break
        last_id = pairs[-1].id

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
                        .values(relationship="resolved", context_scope="unreferenced", tier=2)
                    )
                    await session.commit()
                    continue

                context_scope = await _pair_context_scope(session, pair.sha_a, pair.sha_b)
                if context_scope == "same_gallery_only":
                    logger.info("same_gallery_only: pair %d", pair.id)
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(
                            relationship="same_gallery_only",
                            context_scope=context_scope,
                            reason="same_gallery_variant",
                            suggested_keep=None,
                            tier=2,
                        )
                    )
                    await session.commit()
                    total_processed += 1
                    continue
                if context_scope == "unreferenced":
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(relationship="resolved", context_scope=context_scope, reason="unreferenced", tier=2)
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
                        context_scope=context_scope,
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
