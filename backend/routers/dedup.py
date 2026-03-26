"""Dedup review and stats API endpoints."""

import base64
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

import core.queue
from core.auth import require_role
from core.database import async_session
from core.keys import cursor_hmac_key
from db.models import Blob, BlobRelationship, Image
from services.cas import cas_url, thumb_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dedup"])

_admin = require_role("admin")

REVIEW_RELATIONSHIPS = {"quality_conflict", "variant"}


# ── Cursor helpers ────────────────────────────────────────────────────


def _cursor_secret() -> bytes:
    return cursor_hmac_key()


def _encode_cursor(id: int) -> str:
    payload = base64.urlsafe_b64encode(str(id).encode()).decode()
    sig = hmac.new(_cursor_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _decode_cursor(cursor: str) -> int | None:
    try:
        payload, sig = cursor.rsplit(".", 1)
        expected = hmac.new(_cursor_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return int(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return None


# ── Blob detail helper ────────────────────────────────────────────────


def _blob_detail(blob: Blob) -> dict:
    return {
        "sha256": blob.sha256,
        "width": blob.width,
        "height": blob.height,
        "file_size": blob.file_size,
        "thumb_url": thumb_url(blob.sha256),
        "image_url": cas_url(blob.sha256, blob.extension),
    }


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/stats")
async def get_dedup_stats(_: dict = Depends(_admin)):
    """Return counts by relationship state."""
    async with async_session() as session:
        result = await session.execute(
            select(BlobRelationship.relationship, func.count().label("cnt"))
            .group_by(BlobRelationship.relationship)
        )
        rows = result.all()

        blob_count_result = await session.execute(
            select(func.count()).select_from(Blob).where(Blob.phash_int.isnot(None))
        )
        total_blobs = blob_count_result.scalar_one()

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.relationship] = row.cnt

    return {
        "total_blobs": total_blobs,
        "needs_t2": counts.get("needs_t2", 0),
        "needs_t3": counts.get("needs_t3", 0),
        "pending_review": counts.get("quality_conflict", 0) + counts.get("variant", 0),
        "whitelisted": counts.get("whitelisted", 0),
        "resolved": counts.get("resolved", 0),
    }


@router.get("/review")
async def get_dedup_review(
    relationship: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _: dict = Depends(_admin),
):
    """Return paginated review queue (quality_conflict and variant only)."""
    after_id = _decode_cursor(cursor) if cursor else None

    async with async_session() as session:
        q = (
            select(BlobRelationship)
            .options(
                joinedload(BlobRelationship.blob_a),
                joinedload(BlobRelationship.blob_b),
            )
            .order_by(BlobRelationship.id)
            .limit(limit + 1)
        )

        if relationship and relationship in REVIEW_RELATIONSHIPS:
            q = q.where(BlobRelationship.relationship == relationship)
        else:
            q = q.where(BlobRelationship.relationship.in_(REVIEW_RELATIONSHIPS))

        if after_id is not None:
            q = q.where(BlobRelationship.id > after_id)

        result = await session.execute(q)
        pairs = list(result.scalars().unique())

    has_more = len(pairs) > limit
    pairs = pairs[:limit]
    next_cursor = _encode_cursor(pairs[-1].id) if has_more and pairs else None

    items = []
    for pair in pairs:
        items.append({
            "id": pair.id,
            "relationship": pair.relationship,
            "hamming_dist": pair.hamming_dist,
            "suggested_keep": pair.suggested_keep,
            "reason": pair.reason,
            "diff_score": pair.diff_score,
            "diff_type": pair.diff_type,
            "blob_a": _blob_detail(pair.blob_a),
            "blob_b": _blob_detail(pair.blob_b),
        })

    return {"items": items, "next_cursor": next_cursor}


class KeepRequest(BaseModel):
    keep_sha: str


class ScanStartRequest(BaseModel):
    mode: str  # "reset" or "pending"

class ScanSignalRequest(BaseModel):
    signal: str  # "pause", "resume", or "stop"


@router.post("/review/{pair_id}/keep")
async def keep_blob(
    pair_id: int,
    req: KeepRequest,
    _: dict = Depends(_admin),
):
    """Mark one blob as the keeper; re-point images and resolve the pair."""
    async with async_session() as session:
        result = await session.execute(
            select(BlobRelationship)
            .options(joinedload(BlobRelationship.blob_a), joinedload(BlobRelationship.blob_b))
            .where(BlobRelationship.id == pair_id)
        )
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail="Pair not found")

        keep_sha = req.keep_sha
        discard_sha = pair.sha_b if keep_sha == pair.sha_a else pair.sha_a

        if keep_sha not in (pair.sha_a, pair.sha_b):
            raise HTTPException(status_code=400, detail="keep_sha must be one of the pair")

        # Re-point images from discard_sha to keep_sha
        remap_result = await session.execute(
            update(Image)
            .where(Image.blob_sha256 == discard_sha)
            .values(blob_sha256=keep_sha)
        )
        remapped = remap_result.rowcount or 0

        # Adjust ref_counts by the actual number of remapped images
        if remapped > 0:
            await session.execute(
                update(Blob).where(Blob.sha256 == discard_sha).values(ref_count=Blob.ref_count - remapped)
            )
            await session.execute(
                update(Blob).where(Blob.sha256 == keep_sha).values(ref_count=Blob.ref_count + remapped)
            )

        await session.execute(
            update(BlobRelationship)
            .where(BlobRelationship.id == pair_id)
            .values(relationship="resolved")
        )
        await session.commit()

    from core.events import EventType, emit_safe
    await emit_safe(EventType.DEDUP_PAIR_RESOLVED, actor_user_id=_["user_id"], resource_type="dedup")
    return {"status": "ok"}


@router.post("/review/{pair_id}/whitelist")
async def whitelist_pair(
    pair_id: int,
    _: dict = Depends(_admin),
):
    """Mark a pair as whitelisted (not a duplicate)."""
    async with async_session() as session:
        result = await session.execute(
            select(BlobRelationship).where(BlobRelationship.id == pair_id)
        )
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail="Pair not found")

        await session.execute(
            update(BlobRelationship)
            .where(BlobRelationship.id == pair_id)
            .values(relationship="whitelisted")
        )
        await session.commit()

    return {"status": "ok"}


@router.get("/scan/progress")
async def get_scan_progress(_: dict = Depends(_admin)):
    """Return current dedup scan progress."""
    from core.redis_client import get_redis
    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw is None:
        return {"status": "idle"}

    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw

    current_raw = await r.get("dedup:progress:current")
    total_raw = await r.get("dedup:progress:total")
    tier_raw = await r.get("dedup:progress:tier")
    mode_raw = await r.get("dedup:progress:mode")

    current = int(current_raw) if current_raw else 0
    total = int(total_raw) if total_raw else 0
    tier = int(tier_raw) if tier_raw else 1
    mode = (mode_raw.decode() if isinstance(mode_raw, bytes) else mode_raw) or "pending"

    percent = round(current / total * 100) if total > 0 else 0

    return {
        "status": status,
        "current": current,
        "total": total,
        "tier": tier,
        "mode": mode,
        "percent": percent,
    }


@router.post("/scan/start")
async def start_scan(
    req: ScanStartRequest,
    _: dict = Depends(_admin),
):
    """Enqueue a dedup scan job. 409 if already running/paused."""
    from core.redis_client import get_redis
    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw in (b"running", b"paused", "running", "paused"):
        raise HTTPException(status_code=409, detail="Scan already running")

    if req.mode not in ("reset", "pending"):
        raise HTTPException(status_code=422, detail="mode must be 'reset' or 'pending'")

    await core.queue.enqueue("dedup_scan_job", _job_id="dedup_scan:singleton", mode=req.mode)
    from core.events import EventType, emit_safe
    await emit_safe(EventType.DEDUP_SCAN_STARTED, actor_user_id=_["user_id"], resource_type="system")
    return {"status": "queued"}


@router.post("/scan/signal")
async def send_scan_signal(
    req: ScanSignalRequest,
    _: dict = Depends(_admin),
):
    """Send a pause/resume/stop signal to the running scan. 409 if idle."""
    from core.redis_client import get_redis
    r = get_redis()

    status_raw = await r.get("dedup:progress:status")
    if status_raw is None:
        raise HTTPException(status_code=409, detail="No scan running")

    if req.signal not in ("pause", "resume", "stop"):
        raise HTTPException(status_code=422, detail="signal must be 'pause', 'resume', or 'stop'")

    await r.set("dedup:progress:signal", req.signal)
    return {"status": "ok"}


@router.delete("/review/{pair_id}")
async def dismiss_pair(
    pair_id: int,
    _: dict = Depends(_admin),
):
    """Dismiss a pair (mark as resolved)."""
    async with async_session() as session:
        result = await session.execute(
            select(BlobRelationship).where(BlobRelationship.id == pair_id)
        )
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail="Pair not found")

        await session.execute(
            update(BlobRelationship)
            .where(BlobRelationship.id == pair_id)
            .values(relationship="resolved")
        )
        await session.commit()

    return {"status": "ok"}
