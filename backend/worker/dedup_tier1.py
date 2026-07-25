"""Dedup Tier 1 — pHash scan worker."""

import logging

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import async_session
from core.redis_client import get_redis
from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS
from db.models import Blob, BlobRelationship
from worker.dedup_helpers import DEDUP_SCAN_VERSION, PhashBKTree, _now_iso, _scan_indexed_candidates
from worker.helpers import _cron_record, _cron_should_run

logger = logging.getLogger("worker.dedup_tier1")


async def dedup_tier1_job(ctx: dict, force: bool = False) -> dict:
    """Scan all blobs for similar pairs using perceptual hashing.

    Writes matching pairs into blob_relationships with relationship='needs_context'.
    A BK-tree provides exact Hamming-radius lookup without traversing every
    possible pair, while ``dedup_scanned_threshold`` makes repeated runs
    incremental and re-scans only when the configured radius grows.
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

    # Build the metric index once, but query only blobs that have not previously
    # been scanned at this threshold. A higher threshold re-queues older blobs;
    # lowering it does not destroy existing review decisions.
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
        if not isinstance(blob.dedup_scanned_threshold, int)
        or blob.dedup_scanned_threshold < threshold
        or blob.dedup_scanned_phash_int != blob.phash_int
        or blob.dedup_scanned_version != DEDUP_SCAN_VERSION
    ]
    index = PhashBKTree(blobs)
    total = len(scan_blobs)
    logger.info("Starting indexed scan, threshold=%d, scan_blobs=%d, indexed_blobs=%d", threshold, total, len(blobs))

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

    await _flush()
    await r.set("cron:dedup_tier1:last_run", _now_iso())
    await r.set("cron:dedup_tier1:last_status", f"inserted={total_inserted}")
    logger.info("Done, new pairs inserted: %d", total_inserted)
    return {"status": "ok", "inserted": total_inserted, "scanned": total}
