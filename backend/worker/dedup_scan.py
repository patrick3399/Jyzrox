"""Dedup orchestrator — runs tier 1/2/3 with progress tracking and pause/stop support."""

import logging

from sqlalchemy import delete, func, select

from core.database import async_session
from core.redis_client import get_redis
from db.models import Blob, BlobRelationship, Image
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import update
from worker.dedup_helpers import (
    _MASK64, _MASK16,
    _classify_pair, _now_iso,
    DedupProgress,
)

logger = logging.getLogger("worker.dedup_scan")


async def dedup_scan_job(ctx: dict, mode: str = "pending") -> dict:
    """Orchestrate all dedup tiers with real-time progress tracking.

    mode='pending' — process unprocessed blobs only (skip already-seen pairs)
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
            await session.execute(delete(BlobRelationship))
            await session.commit()
        logger.info("dedup_scan_job: reset — all relationships cleared")

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
                Blob.phash_q0,
                Blob.phash_q1,
                Blob.phash_q2,
                Blob.phash_q3,
            )
            .where(Blob.phash_int.isnot(None))
            .order_by(Blob.sha256)
        )
        blobs = result.all()

    total_blobs = len(blobs)
    logger.info("Tier 1 start, threshold=%d, blobs=%d", threshold, total_blobs)
    await progress.start(mode, total=total_blobs, tier=1)

    total_inserted = 0
    pairs_batch: list[dict] = []

    async def _flush() -> None:
        nonlocal total_inserted
        if not pairs_batch:
            return
        async with async_session() as session:
            stmt = pg_insert(BlobRelationship).values(pairs_batch)
            stmt = stmt.on_conflict_do_nothing(constraint="uq_blob_pair")
            res = await session.execute(stmt)
            await session.commit()
            total_inserted += res.rowcount or 0
        pairs_batch.clear()

    for i, a in enumerate(blobs):
        a_q0 = (a.phash_q0 or 0) & _MASK16
        a_q1 = (a.phash_q1 or 0) & _MASK16
        a_phash = a.phash_int & _MASK64

        for b in blobs[i + 1:]:
            q01_dist = (
                bin(a_q0 ^ ((b.phash_q0 or 0) & _MASK16)).count('1')
                + bin(a_q1 ^ ((b.phash_q1 or 0) & _MASK16)).count('1')
            )
            if q01_dist > threshold:
                continue

            dist = bin(a_phash ^ (b.phash_int & _MASK64)).count('1')
            if dist > threshold:
                continue

            pairs_batch.append({
                "sha_a": a.sha256,
                "sha_b": b.sha256,
                "hamming_dist": dist,
                "relationship": "needs_t2",
                "tier": 1,
            })

            if len(pairs_batch) >= 1000:
                await _flush()

        await progress.report(1)
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
    logger.info("Tier 1 done, new pairs inserted: %d", total_inserted)

    # ── Tier 2 — heuristic classify ────────────────────────────────────
    heuristic_raw = await r.get("setting:dedup_heuristic_enabled")
    heuristic_enabled = heuristic_raw == b"1"
    opencv_raw = await r.get("setting:dedup_opencv_enabled")
    opencv_enabled = opencv_raw == b"1"

    async with async_session() as session:
        count_result = await session.execute(
            select(func.count()).where(BlobRelationship.relationship == "needs_t2")
        )
        needs_t2_count = count_result.scalar_one()

    await progress.advance_tier(2, total=needs_t2_count)
    logger.info("Tier 2 start, needs_t2=%d", needs_t2_count)

    t2_processed = 0
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
                    t2_processed += 1
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
                t2_processed += 1

        await progress.report(len(pairs))
        signal = await progress.check_signal()
        if signal == "pause":
            resumed = await progress.wait_for_resume()
            if not resumed:
                await progress.finish()
                return {"status": "stopped", "tier": 2}
        elif signal == "stop":
            await progress.finish()
            return {"status": "stopped", "tier": 2}

    logger.info("Tier 2 done, processed: %d", t2_processed)

    # ── Tier 3 — OpenCV pixel-diff ─────────────────────────────────────
    if not opencv_enabled:
        logger.info("OpenCV disabled — skipping tier 3")
        await progress.finish()
        return {"status": "ok", "tier1_inserted": total_inserted, "tier2_processed": t2_processed}

    import asyncio
    from services.cas import resolve_blob_path
    from worker.dedup_helpers import _opencv_pixel_diff

    threshold_cv_raw = await r.get("setting:dedup_opencv_threshold")
    threshold_cv = float(threshold_cv_raw) if threshold_cv_raw else 0.85

    async with async_session() as session:
        count_result = await session.execute(
            select(func.count()).where(BlobRelationship.relationship == "needs_t3")
        )
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
    return {
        "status": "ok",
        "tier1_inserted": total_inserted,
        "tier2_processed": t2_processed,
        "tier3_processed": t3_processed,
    }
