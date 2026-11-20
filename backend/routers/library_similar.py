"""Library split from routers/library.py (library_similar)."""

from itertools import combinations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import column as sql_column
from sqlalchemy.sql import text as sql_text

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from db.models import (
    Gallery,
    Image,
)
from services.cas import (
    cas_url,
    library_url,
)
from services.cas import thumb_srcset as cas_thumb_srcset
from services.cas import thumb_url as cas_thumb_url
from services.library_serializers import is_pending as _is_pending

router = APIRouter()


def _hamming_neighbors_all(quarters: list[int], max_dist: int) -> list[set[int]]:
    """Generate all 16-bit signed integer neighbors within Hamming distance max_dist for each quarter.

    For max_dist=0: 1 value per quarter (exact match only)
    For max_dist=1: 17 values per quarter (C(16,0) + C(16,1))
    For max_dist=2: 137 values per quarter (C(16,0) + C(16,1) + C(16,2))
    """
    result = []
    for q_val in quarters:
        uval = q_val & 0xFFFF
        neighbors: set[int] = set()
        for dist in range(max_dist + 1):
            if dist == 0:
                neighbors.add(q_val)
            else:
                for bits in combinations(range(16), dist):
                    flipped = uval
                    for b in bits:
                        flipped ^= 1 << b
                    signed = flipped - 0x10000 if flipped >= 0x8000 else flipped
                    neighbors.add(signed)
        result.append(neighbors)
    return result


@router.get("/images/{image_id}/similar")
async def find_similar_images(
    image_id: int,
    threshold: int = Query(default=10, ge=0, le=32),
    limit: int = Query(default=20, ge=1, le=100),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Find visually similar images by perceptual hash Hamming distance.

    Uses pigeonhole pre-filter on pHash quarter columns for indexed lookup,
    then exact Hamming distance on candidates. At 10M images, pre-filter
    returns ~1K-10K candidates instead of scanning all rows.
    Threshold 0 = exact match, 10 = visually similar (recommended default),
    32 = very loose match.
    """
    img_row = (
        await db.execute(
            select(Image)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, gallery_access_filter(auth))
            .options(selectinload(Image.blob))
        )
    ).scalar_one_or_none()
    if not img_row:
        raise HTTPException(status_code=404, detail="Image not found")
    if _is_pending(img_row):
        raise HTTPException(status_code=409, detail="Image is still being processed")
    if not img_row.blob or not img_row.blob.phash:
        raise HTTPException(status_code=400, detail="Image has no perceptual hash")

    phash = img_row.blob.phash
    phash_int_val = int(phash, 16)

    def _to_signed16(v: int) -> int:
        return v - 0x10000 if v >= 0x8000 else v

    quarters = [
        _to_signed16((phash_int_val >> 48) & 0xFFFF),
        _to_signed16((phash_int_val >> 32) & 0xFFFF),
        _to_signed16((phash_int_val >> 16) & 0xFFFF),
        _to_signed16(phash_int_val & 0xFFFF),
    ]

    max_quarter_dist = threshold // 4  # floor(T/4) — pigeonhole guarantee
    params: dict = {"phash_int": phash_int_val, "image_id": image_id, "threshold": threshold}

    if max_quarter_dist > 2 or threshold > 11:
        # For loose thresholds the neighbor sets become large (>137 per quarter);
        # fall back to full scan on phash_int with exact bit_count filter.
        candidates = sql_text("""
            SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                   i.external_path, b.phash,
                   bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
            FROM images i
            JOIN blobs b ON i.blob_sha256 = b.sha256
            WHERE b.phash_int IS NOT NULL
              AND i.id != :image_id
              AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
        """)
    else:
        # Phase 1: generate Hamming neighborhoods for each quarter
        neighbors = _hamming_neighbors_all(quarters, max_quarter_dist)

        # Guard: if the combined neighbor sets are too large the ANY() arrays
        # become counterproductive — fall back to the full scan path instead.
        total_neighbors = sum(len(s) for s in neighbors)
        if total_neighbors > 10000:
            candidates = sql_text("""
                SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                       i.external_path, b.phash,
                       bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
            """)
        else:
            # Phase 2: indexed pre-filter — OR across all four quarter columns,
            # then exact bit_count check on the surviving candidates only.
            conditions = []
            for qi, neighbor_set in enumerate(neighbors):
                param_name = f"q{qi}_neighbors"
                conditions.append(f"b.phash_q{qi} = ANY(:{param_name})")
                params[param_name] = list(neighbor_set)

            where_prefilter = " OR ".join(conditions)

            candidates = sql_text(f"""
                SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                       i.external_path, b.phash,
                       bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int AS distance
                FROM images i
                JOIN blobs b ON i.blob_sha256 = b.sha256
                WHERE b.phash_int IS NOT NULL
                  AND i.id != :image_id
                  AND ({where_prefilter})
                  AND bit_count((:phash_int ::bigint # b.phash_int)::bit(64))::int <= :threshold
            """)

    # Candidates carry CAS URLs (capabilities, see docs/security-model.md BR-006),
    # so drop the ones from galleries the caller cannot read before ranking.
    sim = candidates.columns(
        sql_column("id"),
        sql_column("gallery_id"),
        sql_column("filename"),
        sql_column("sha256"),
        sql_column("extension"),
        sql_column("external_path"),
        sql_column("phash"),
        sql_column("distance"),
    ).subquery("sim")
    results = (
        await db.execute(
            select(sim)
            .join(Gallery, Gallery.id == sim.c.gallery_id)
            .where(gallery_access_filter(auth))
            .order_by(sim.c.distance.asc())
            .limit(limit),
            params,
        )
    ).all()

    def _row_to_url(r) -> str:
        if r.external_path:
            return library_url(r.external_path)
        return cas_url(r.sha256, r.extension)

    return {
        "image_id": image_id,
        "phash": phash,
        "similar": [
            {
                "id": r.id,
                "gallery_id": r.gallery_id,
                "filename": r.filename,
                "file_path": _row_to_url(r),
                "thumb_path": cas_thumb_url(r.sha256),
                "thumb_srcset": cas_thumb_srcset(r.sha256),
                "phash": r.phash,
                "distance": r.distance,
            }
            for r in results
        ],
    }
