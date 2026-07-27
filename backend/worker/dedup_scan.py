"""Dedup orchestrator — runs tier 1/2/3 with progress tracking and pause/stop support."""

import logging

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, joinedload

from core.database import async_session
from core.redis_client import get_redis
from db.models import Blob, BlobRelationship
from worker.dedup_helpers import (
    DEDUP_SCAN_VERSION,
    DedupProgress,
    PhashBKTree,
    _classify_pair,
    _pair_context_scopes,
    _scan_indexed_candidates,
)

logger = logging.getLogger("worker.dedup_scan")


async def dedup_scan_job(ctx: dict, mode: str = "pending") -> dict:
    try:
        return await _dedup_scan_job_impl(ctx, mode)
    except Exception as exc:
        await DedupProgress(get_redis()).fail(str(exc))
        logger.exception("dedup_scan_job failed")
        raise


async def _dedup_scan_job_impl(ctx: dict, mode: str = "pending") -> dict:
    """Orchestrate all dedup tiers with real-time progress tracking.

    mode='pending' — query only blobs not yet scanned at the active threshold
    mode='reset'   — DELETE all blob_relationships first, then full re-scan
    """
    r = get_redis()

    # Guard against double-start
    current_status = await r.get(DedupProgress.STATUS_KEY)
    if current_status in (b"running", b"paused", "running", "paused"):
        logger.warning("dedup_scan_job: already running, aborting")
        return {"status": "already_running"}

    progress = DedupProgress(r)

    # ── Mode: reset ───────────────────────────────────────────────────
    if mode == "reset":
        async with async_session() as session:
            await session.execute(
                delete(BlobRelationship).where(
                    BlobRelationship.decision.is_(None),
                    BlobRelationship.relationship.notin_(("whitelisted", "resolved")),
                )
            )
            await session.execute(
                update(Blob).values(
                    dedup_scanned_threshold=None,
                    dedup_scanned_phash_int=None,
                    dedup_scanned_version=None,
                )
            )
            await session.commit()
        logger.info("dedup_scan_job: reset — automatic relationships cleared; review decisions preserved")

    # ── Tier 1 — pHash scan ───────────────────────────────────────────
    enabled = await r.get("setting:dedup_phash_enabled")
    if not enabled or enabled == b"0":
        logger.info("pHash disabled — skipping all tiers")
        return {"status": "skipped", "reason": "disabled"}

    threshold_raw = await r.get("setting:dedup_phash_threshold")
    threshold = int(threshold_raw) if threshold_raw else 10

    async with async_session() as session:
        result = await session.execute(
            select(
                Blob.sha256,
                Blob.phash_int,
                Blob.dedup_scanned_threshold,
                Blob.dedup_scanned_phash_int,
                Blob.dedup_scanned_version,
            )
            .where(Blob.phash_int.isnot(None))
            .order_by(Blob.sha256)
        )
        blobs = result.all()

    scan_blobs = [
        blob
        for blob in blobs
        if mode == "reset"
        or not isinstance(blob.dedup_scanned_threshold, int)
        or blob.dedup_scanned_threshold < threshold
        or blob.dedup_scanned_phash_int != blob.phash_int
        or blob.dedup_scanned_version != DEDUP_SCAN_VERSION
    ]
    index = PhashBKTree(blobs)
    total_blobs = len(scan_blobs)
    logger.info(
        "Tier 1 indexed start, threshold=%d, scan_blobs=%d, indexed_blobs=%d", threshold, total_blobs, len(blobs)
    )
    await progress.start(mode, total=total_blobs, tier=1)

    total_inserted = 0
    pairs_batch: list[dict] = []
    pair_keys: set[tuple[str, str]] = set()
    scanned_batch: list[str] = []

    async def _flush() -> None:
        nonlocal total_inserted
        if not pairs_batch and not scanned_batch:
            return
        async with async_session() as session:
            inserted = 0
            if pairs_batch:
                stmt = pg_insert(BlobRelationship).values(pairs_batch)
                stmt = stmt.on_conflict_do_nothing(constraint="uq_blob_pair")
                res = await session.execute(stmt)
                inserted = int(getattr(res, "rowcount", 0) or 0)
            if scanned_batch:
                await session.execute(
                    update(Blob)
                    .where(Blob.sha256.in_(scanned_batch))
                    .values(
                        dedup_scanned_threshold=threshold,
                        dedup_scanned_phash_int=Blob.phash_int,
                        dedup_scanned_version=DEDUP_SCAN_VERSION,
                    )
                )
            await session.commit()
            total_inserted += inserted
        pairs_batch.clear()
        scanned_batch.clear()

    progress_pending = 0
    for a in scan_blobs:
        for b, dist in _scan_indexed_candidates(index, a, threshold):
            sha_a, sha_b = sorted((a.sha256, b.sha256))
            pair_key = (sha_a, sha_b)
            if pair_key in pair_keys:
                continue
            pair_keys.add(pair_key)
            pairs_batch.append(
                {
                    "sha_a": sha_a,
                    "sha_b": sha_b,
                    "hamming_dist": dist,
                    "relationship": "needs_context",
                    "tier": 1,
                }
            )

            if len(pairs_batch) >= 1000:
                await _flush()

        scanned_batch.append(a.sha256)
        if len(scanned_batch) >= 250:
            await _flush()
        progress_pending += 1
        if progress_pending < 100:
            continue
        await progress.report(progress_pending)
        progress_pending = 0
        signal = await progress.check_signal()
        if signal == "pause":
            await _flush()
            resumed = await progress.wait_for_resume()
            if not resumed:
                await progress.finish()
                return {"status": "stopped", "tier": 1}
        elif signal == "stop":
            await _flush()
            await progress.finish()
            return {"status": "stopped", "tier": 1}

    await _flush()
    if progress_pending:
        await progress.report(progress_pending)
        signal = await progress.check_signal()
        if signal == "pause":
            resumed = await progress.wait_for_resume()
            if not resumed:
                await progress.finish()
                return {"status": "stopped", "tier": 1}
        elif signal == "stop":
            await progress.finish()
            return {"status": "stopped", "tier": 1}
    logger.info("Tier 1 done, new pairs inserted: %d", total_inserted)

    # ── Mandatory occurrence context gate + optional Tier 2 heuristic ─
    heuristic_raw = await r.get("setting:dedup_heuristic_enabled")
    heuristic_enabled = heuristic_raw == b"1"
    opencv_raw = await r.get("setting:dedup_opencv_enabled")
    opencv_enabled = opencv_raw == b"1"

    context_states = (
        "needs_context",
        "needs_t2",
        "same_gallery_only",
        "needs_review",
        "quality_conflict",
        "variant",
        "needs_t3",
    )
    context_blob_a = aliased(Blob)
    context_blob_b = aliased(Blob)
    context_is_dirty = or_(
        BlobRelationship.context_revision_a.is_distinct_from(context_blob_a.occurrence_revision),
        BlobRelationship.context_revision_b.is_distinct_from(context_blob_b.occurrence_revision),
    )
    actionable_context = or_(
        BlobRelationship.relationship.in_(("needs_context", "needs_t2")),
        and_(BlobRelationship.relationship == "same_gallery_only", context_is_dirty),
        and_(
            BlobRelationship.relationship == "needs_review",
            or_(context_is_dirty, heuristic_enabled, opencv_enabled),
        ),
        and_(BlobRelationship.relationship.in_(("quality_conflict", "variant")), context_is_dirty),
        and_(
            BlobRelationship.relationship == "needs_t3",
            or_(context_is_dirty, not opencv_enabled),
        ),
    )
    async with async_session() as session:
        count_result = await session.execute(
            select(func.count())
            .select_from(BlobRelationship)
            .join(context_blob_a, context_blob_a.sha256 == BlobRelationship.sha_a)
            .join(context_blob_b, context_blob_b.sha256 == BlobRelationship.sha_b)
            .where(
                BlobRelationship.relationship.in_(context_states),
                BlobRelationship.decision.is_(None),
                actionable_context,
            )
        )
        context_count = count_result.scalar_one()

    active_stage = 2 if heuristic_enabled else 1
    await progress.advance_tier(active_stage, total=context_count)
    logger.info(
        "Context gate start, candidates=%d, heuristic_enabled=%s",
        context_count,
        heuristic_enabled,
    )

    t2_processed = 0
    last_t2_id = 0
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
                    BlobRelationship.relationship.in_(context_states),
                    BlobRelationship.decision.is_(None),
                    actionable_context,
                )
                .where(BlobRelationship.id > last_t2_id)
                .order_by(BlobRelationship.id)
                .limit(500)
            )
            pairs = list(result.scalars().unique())
            if not pairs:
                break
            last_t2_id = pairs[-1].id

            context_dirty = [
                pair
                for pair in pairs
                if pair.relationship in ("needs_context", "needs_t2")
                or pair.context_revision_a != getattr(pair.blob_a, "occurrence_revision", None)
                or pair.context_revision_b != getattr(pair.blob_b, "occurrence_revision", None)
            ]
            context_dirty_ids = {pair.id for pair in context_dirty}
            scopes = await _pair_context_scopes(session, context_dirty)

            for pair in pairs:
                blob_a = pair.blob_a
                blob_b = pair.blob_b
                is_context_dirty = pair.id in context_dirty_ids
                if not blob_a or not blob_b:
                    pair.relationship = "resolved"
                    pair.context_scope = "unreferenced"
                    pair.reason = "unreferenced"
                    pair.tier = 1
                    t2_processed += 1
                    continue

                if is_context_dirty:
                    pair.context_scope = scopes.get(pair.id, "unreferenced")
                    pair.context_revision_a = blob_a.occurrence_revision
                    pair.context_revision_b = blob_b.occurrence_revision

                if pair.context_scope == "same_gallery_only":
                    if is_context_dirty:
                        pair.relationship = "same_gallery_only"
                        pair.reason = "same_gallery_variant"
                        pair.suggested_keep = None
                        pair.tier = 1
                        t2_processed += 1
                    continue
                if pair.context_scope == "unreferenced":
                    pair.relationship = "resolved"
                    pair.reason = "unreferenced"
                    pair.suggested_keep = None
                    pair.tier = 1
                    t2_processed += 1
                    continue

                if opencv_enabled:
                    if heuristic_enabled:
                        _, keep, reason = _classify_pair(blob_a, blob_b, True)
                        pair.suggested_keep = keep
                        pair.reason = reason
                        pair.tier = 2
                    else:
                        pair.suggested_keep = None
                        pair.reason = None
                        pair.tier = 1
                    pair.relationship = "needs_t3"
                    t2_processed += 1
                elif heuristic_enabled:
                    rel, keep, reason = _classify_pair(blob_a, blob_b, True)
                    pair.relationship = rel
                    pair.suggested_keep = keep
                    pair.reason = reason
                    pair.tier = 2
                    t2_processed += 1
                elif is_context_dirty:
                    pair.relationship = "needs_review"
                    pair.suggested_keep = None
                    pair.reason = None
                    pair.tier = 1
                    t2_processed += 1

            await session.commit()

        await progress.report(len(pairs))
        signal = await progress.check_signal()
        if signal == "pause":
            resumed = await progress.wait_for_resume()
            if not resumed:
                await progress.finish()
                return {"status": "stopped", "tier": active_stage}
        elif signal == "stop":
            await progress.finish()
            return {"status": "stopped", "tier": active_stage}

    logger.info(
        "Context gate done, changed=%d, heuristic_enabled=%s",
        t2_processed,
        heuristic_enabled,
    )

    # ── Tier 3 — OpenCV pixel-diff ─────────────────────────────────────
    if not opencv_enabled:
        logger.info("OpenCV disabled — skipping tier 3")
        await progress.finish()

        from core.events import EventType, emit_safe

        await emit_safe(EventType.DEDUP_SCAN_COMPLETED, resource_type="system", mode=mode)

        return {"status": "ok", "tier1_inserted": total_inserted, "tier2_processed": t2_processed}

    import asyncio

    from services.cas import resolve_readable_blob_path
    from worker.dedup_helpers import _opencv_pixel_diff

    threshold_cv_raw = await r.get("setting:dedup_opencv_threshold")
    threshold_cv = float(threshold_cv_raw) if threshold_cv_raw else 0.85

    async with async_session() as session:
        count_result = await session.execute(select(func.count()).where(BlobRelationship.relationship == "needs_t3"))
        needs_t3_count = count_result.scalar_one()

    await progress.advance_tier(3, total=needs_t3_count)
    logger.info("Tier 3 start, needs_t3=%d", needs_t3_count)

    t3_processed = 0
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

                resolved_a = await resolve_readable_blob_path(session, blob_a)
                resolved_b = await resolve_readable_blob_path(session, blob_b)
                if resolved_a is None or resolved_b is None:
                    # Genuinely gone, not merely a stale scalar path — record it
                    # as unresolvable rather than reporting a pixel mismatch.
                    logger.warning(
                        "[dedup] pair %d: no readable file for %s",
                        pair.id,
                        pair.sha_a if resolved_a is None else pair.sha_b,
                    )
                    await session.execute(
                        update(BlobRelationship)
                        .where(BlobRelationship.id == pair.id)
                        .values(relationship="quality_conflict", tier=3)
                    )
                    await session.commit()
                    continue
                path_a = str(resolved_a)
                path_b = str(resolved_b)

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

                if score >= threshold_cv:
                    heuristic_raw2 = await r.get("setting:dedup_heuristic_enabled")
                    heuristic_enabled2 = heuristic_raw2 == b"1"
                    rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled2)
                    final_keep = pair.suggested_keep or keep
                    final_reason = pair.reason or reason
                else:
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
                t3_processed += 1

        await progress.report(len(pairs))
        signal = await progress.check_signal()
        if signal == "pause":
            resumed = await progress.wait_for_resume()
            if not resumed:
                await progress.finish()
                return {"status": "stopped", "tier": 3}
        elif signal == "stop":
            await progress.finish()
            return {"status": "stopped", "tier": 3}

    await progress.finish()
    logger.info("Tier 3 done, processed: %d", t3_processed)

    from core.events import EventType, emit_safe

    await emit_safe(EventType.DEDUP_SCAN_COMPLETED, resource_type="system", mode=mode)

    return {
        "status": "ok",
        "tier1_inserted": total_inserted,
        "tier2_processed": t2_processed,
        "tier3_processed": t3_processed,
    }
