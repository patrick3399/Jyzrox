"""Dedup Tier 1 — pHash scan worker."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import async_session
from core.redis_client import get_redis
from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
from db.models import Blob, BlobRelationship
from worker.dedup_helpers import _now_iso, _scan_candidates
from worker.helpers import _cron_record, _cron_should_run

logger = logging.getLogger("worker.dedup_tier1")


async def dedup_tier1_job(ctx: dict, force: bool = False) -> dict:
    """Scan all blobs for similar pairs using perceptual hashing.

    Writes matching pairs into blob_relationships with relationship='needs_t2'.
    Uses a pigeonhole pre-filter on pHash quadrants (q0+q1) to skip obviously
    dissimilar pairs before computing the full 64-bit Hamming distance.
    """
    defn = CONFIGURABLE_TASK_DEFS["dedup_tier1"]
    if not force and not await _cron_should_run(ctx, defn.task_id, defn.default_cron, defn.default_enabled):
        logger.info("cron gate not reached — skip")
        return {"status": "skipped", "reason": "cron_gate"}
    await _cron_record(ctx, defn.task_id, "running")
    try:
        result = await _scan_all_blobs()
    except Exception as exc:
        await _cron_record(ctx, defn.task_id, "failed", str(exc))
        raise
    status = result.get("status", "ok")
    await _cron_record(ctx, defn.task_id, "ok" if status == "ok" else result.get("reason", status))
    return result


async def _scan_all_blobs() -> dict:
    r = get_redis()

    enabled = await r.get("setting:dedup_phash_enabled")
    if not enabled or enabled == b"0":
        logger.info("pHash disabled — skip")
        return {"status": "skipped", "reason": "disabled"}

    threshold_raw = await r.get("setting:dedup_phash_threshold")
    threshold = int(threshold_raw) if threshold_raw else 10

    total_inserted = 0

    # Load ALL blobs with phash into memory once — eliminates N individual DB queries
    async with async_session() as session:
        result = await session.execute(
            select(
                Blob.sha256,
                Blob.phash_int,
                Blob.phash_q0,
                Blob.phash_q1,
            )
            .where(Blob.phash_int.isnot(None))
            .order_by(Blob.sha256)  # canonical order: blobs[i].sha256 < blobs[j].sha256
        )
        blobs = result.all()

    total = len(blobs)
    logger.info("Starting scan, threshold=%d, total_blobs=%d", threshold, total)

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

    for i in range(total):
        a = blobs[i]
        # Index-based scan (no slicing) — see worker.dedup_helpers._scan_candidates.
        for b, dist in _scan_candidates(blobs, i, threshold):
            # sha256 already in ascending order (ORDER BY sha256 above)
            pairs_batch.append(
                {
                    "sha_a": a.sha256,
                    "sha_b": b.sha256,
                    "hamming_dist": dist,
                    "relationship": "needs_t2",
                    "tier": 1,
                }
            )

            if len(pairs_batch) >= 1000:
                await _flush()

    await _flush()
    await r.set("cron:dedup_tier1:last_run", _now_iso())
    await r.set("cron:dedup_tier1:last_status", f"inserted={total_inserted}")
    logger.info("Done, new pairs inserted: %d", total_inserted)
    return {"status": "ok", "inserted": total_inserted}
