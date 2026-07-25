"""Dedup Tier 2 — heuristic classify worker."""

import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased, joinedload

from core.database import async_session
from core.redis_client import get_redis
from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
from db.models import Blob, BlobRelationship
from worker.dedup_helpers import _classify_pair, _now_iso, _pair_context_scopes
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
    if not heuristic_enabled:
        logger.info("heuristic disabled — skip Tier 2")
        return {"status": "skipped", "reason": "disabled"}

    opencv_raw = await r.get("setting:dedup_opencv_enabled")
    opencv_enabled = opencv_raw == b"1"

    total_processed = 0
    context_blob_a = aliased(Blob)
    context_blob_b = aliased(Blob)
    context_is_dirty = or_(
        BlobRelationship.context_revision_a.is_distinct_from(context_blob_a.occurrence_revision),
        BlobRelationship.context_revision_b.is_distinct_from(context_blob_b.occurrence_revision),
    )
    actionable = or_(
        BlobRelationship.relationship.in_(("needs_context", "needs_t2", "needs_review")),
        and_(BlobRelationship.relationship == "same_gallery_only", context_is_dirty),
        and_(BlobRelationship.relationship.in_(("quality_conflict", "variant", "needs_t3")), context_is_dirty),
        and_(BlobRelationship.relationship == "needs_t3", not opencv_enabled),
    )

    last_id = 0
    while True:
        async with async_session() as session:
            result = await session.execute(
                select(BlobRelationship)
                .join(context_blob_a, context_blob_a.sha256 == BlobRelationship.sha_a)
                .join(context_blob_b, context_blob_b.sha256 == BlobRelationship.sha_b)
                .options(
                    joinedload(BlobRelationship.blob_a),
                    joinedload(BlobRelationship.blob_b),
                )
                .where(
                    BlobRelationship.relationship.in_(
                        (
                            "needs_context",
                            "needs_t2",
                            "needs_review",
                            "same_gallery_only",
                            "quality_conflict",
                            "variant",
                            "needs_t3",
                        )
                    )
                )
                .where(BlobRelationship.decision.is_(None), actionable)
                .where(BlobRelationship.id > last_id)
                .order_by(BlobRelationship.id)
                .limit(500)
            )
            pairs = list(result.scalars().unique())
            if not pairs:
                break
            last_id = pairs[-1].id
            context_dirty = [
                pair
                for pair in pairs
                if pair.relationship in ("needs_context", "needs_t2")
                or pair.context_revision_a != getattr(pair.blob_a, "occurrence_revision", None)
                or pair.context_revision_b != getattr(pair.blob_b, "occurrence_revision", None)
            ]
            dirty_ids = {pair.id for pair in context_dirty}
            scopes = await _pair_context_scopes(session, context_dirty)

            for pair in pairs:
                blob_a = pair.blob_a
                blob_b = pair.blob_b
                if not blob_a or not blob_b:
                    pair.relationship = "resolved"
                    pair.context_scope = "unreferenced"
                    pair.reason = "unreferenced"
                    pair.tier = 1
                    total_processed += 1
                    continue
                if pair.id in dirty_ids:
                    pair.context_scope = scopes.get(pair.id, "unreferenced")
                    pair.context_revision_a = blob_a.occurrence_revision
                    pair.context_revision_b = blob_b.occurrence_revision
                if pair.context_scope == "same_gallery_only":
                    if pair.id in dirty_ids:
                        pair.relationship = "same_gallery_only"
                        pair.reason = "same_gallery_variant"
                        pair.suggested_keep = None
                        pair.tier = 1
                        total_processed += 1
                    continue
                if pair.context_scope == "unreferenced":
                    pair.relationship = "resolved"
                    pair.reason = "unreferenced"
                    pair.suggested_keep = None
                    pair.tier = 1
                    total_processed += 1
                    continue

                rel, keep, reason = _classify_pair(blob_a, blob_b, True)
                pair.relationship = "needs_t3" if opencv_enabled else rel
                pair.suggested_keep = keep
                pair.reason = reason
                pair.tier = 2
                total_processed += 1

            await session.commit()

    await r.set("cron:dedup_tier2:last_run", _now_iso())
    await r.set("cron:dedup_tier2:last_status", f"processed={total_processed}")
    logger.info("Done, processed: %d", total_processed)
    return {"status": "ok", "processed": total_processed}
