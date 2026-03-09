"""Local library CRUD — queries galleries/images tables via GIN index."""

import base64
import json
import logging
from datetime import UTC, datetime
from itertools import combinations
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, cast, desc, func, not_, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from db.models import Blob, BlockedTag, Gallery, Image, ReadProgress
from services.cas import cas_url, decrement_ref_count, library_dir, resolve_blob_path, thumb_dir, thumb_url as cas_thumb_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])


# ── Cursor helpers ────────────────────────────────────────────────────


def _encode_cursor(gallery: Gallery, sort: str) -> str:
    """Encode sort key + id into a URL-safe base64 cursor string."""
    sort_val = {
        "added_at": gallery.added_at.isoformat() if gallery.added_at else "",
        "rating": gallery.rating,
        "pages": gallery.pages if gallery.pages is not None else 0,
    }[sort]
    payload = {"id": gallery.id, "v": str(sort_val), "s": sort}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + "=="))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


# ── Gallery list ─────────────────────────────────────────────────────


async def _get_blocked_tag_strings(db: AsyncSession, user_id: int) -> list[str]:
    """Return list of 'namespace:name' blocked tag strings for the user."""
    rows = (
        await db.execute(
            select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id)
        )
    ).all()
    return [f"{r.namespace}:{r.name}" for r in rows]


@router.get("/galleries")
async def list_galleries(
    q: str = Query(default=""),
    tags: list[str] = Query(default=[]),
    exclude_tags: list[str] = Query(default=[]),
    favorited: bool | None = Query(default=None),
    min_rating: int | None = Query(default=None, ge=0, le=5),
    source: str | None = Query(default=None),
    import_mode: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    sort: Literal["added_at", "rating", "pages"] = Query(default="added_at"),
    cursor: str | None = Query(default=None),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Search local library.
    Tag filtering uses tags_array GIN index for performance:
      tags=character:rem&tags=general:blue_hair → AND
      exclude_tags=general:sketch              → NOT

    Supports two pagination modes:
      - cursor-based (preferred): pass cursor= from previous response's next_cursor.
        No COUNT(*), O(1) seek via compound index.
      - page-based (legacy): pass page= integer. Capped at page 500.
    """
    stmt = select(Gallery)

    # GIN array operations
    if tags:
        stmt = stmt.where(Gallery.tags_array.contains(tags))
    if exclude_tags:
        stmt = stmt.where(not_(Gallery.tags_array.overlap(exclude_tags)))
    if favorited is not None:
        stmt = stmt.where(Gallery.favorited == favorited)
    if min_rating is not None:
        stmt = stmt.where(Gallery.rating >= min_rating)
    if source:
        stmt = stmt.where(Gallery.source == source)
    if q:
        stmt = stmt.where(Gallery.title.ilike(f"%{q}%"))

    # Filter out galleries containing blocked tags
    user_id = auth["user_id"]
    blocked_tags = await _get_blocked_tag_strings(db, user_id)
    if blocked_tags:
        stmt = stmt.where(not_(Gallery.tags_array.overlap(cast(blocked_tags, ARRAY(Text)))))

    sort_col = {"added_at": Gallery.added_at, "rating": Gallery.rating, "pages": Gallery.pages}[sort]

    if cursor is not None:
        # Keyset pagination — no COUNT(*), no OFFSET
        c = _decode_cursor(cursor)
        if c.get("s") != sort:
            raise HTTPException(status_code=400, detail="Cursor sort key does not match current sort parameter")

        cursor_id = c["id"]
        cursor_val = c["v"]

        # For all supported sorts we use DESC order, so "next page" means
        # (sort_val, id) strictly less than cursor values (tie-break on id DESC).
        if sort == "added_at":
            from datetime import datetime as _dt

            try:
                parsed = _dt.fromisoformat(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.added_at < parsed,
                    and_(Gallery.added_at == parsed, Gallery.id < cursor_id),
                )
            )
        elif sort == "rating":
            try:
                cv = int(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.rating < cv,
                    and_(Gallery.rating == cv, Gallery.id < cursor_id),
                )
            )
        else:  # pages
            try:
                cv = int(cursor_val)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid cursor value")
            stmt = stmt.where(
                or_(
                    Gallery.pages < cv,
                    and_(Gallery.pages == cv, Gallery.id < cursor_id),
                )
            )

        stmt = stmt.order_by(desc(sort_col), desc(Gallery.id)).limit(limit + 1)
        rows = (await db.execute(stmt)).scalars().all()

        has_next = len(rows) > limit
        if has_next:
            rows = rows[:limit]

        next_cursor = _encode_cursor(rows[-1], sort) if has_next and rows else None

        gallery_ids = [g.id for g in rows]
        if gallery_ids:
            cover_stmt = (
                select(Image.gallery_id, Blob.sha256)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .where(Image.gallery_id.in_(gallery_ids), Image.page_num == 1)
            )
            cover_rows = (await db.execute(cover_stmt)).all()
            cover_map = {r.gallery_id: cas_thumb_url(r.sha256) for r in cover_rows}
        else:
            cover_map = {}

        return {
            "galleries": [_g(g, cover_thumb=cover_map.get(g.id)) for g in rows],
            "next_cursor": next_cursor,
            "has_next": has_next,
        }

    else:
        # Legacy page-based pagination — keep COUNT(*) for backward compat
        if page > 500:
            raise HTTPException(status_code=400, detail="Page depth exceeds limit. Use cursor= for deep pagination.")

        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = stmt.order_by(desc(sort_col), desc(Gallery.id)).offset(page * limit).limit(limit)
        galleries = (await db.execute(stmt)).scalars().all()

        gallery_ids = [g.id for g in galleries]
        if gallery_ids:
            cover_stmt = (
                select(Image.gallery_id, Blob.sha256)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .where(Image.gallery_id.in_(gallery_ids), Image.page_num == 1)
            )
            cover_rows = (await db.execute(cover_stmt)).all()
            cover_map = {r.gallery_id: cas_thumb_url(r.sha256) for r in cover_rows}
        else:
            cover_map = {}

        return {"total": total, "page": page, "galleries": [_g(g, cover_thumb=cover_map.get(g.id)) for g in galleries]}


@router.get("/galleries/{gallery_id}")
async def get_gallery(
    gallery_id: int,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404(db, gallery_id)
    cover_row = (
        await db.execute(
            select(Blob.sha256)
            .join(Image, Image.blob_sha256 == Blob.sha256)
            .where(Image.gallery_id == gallery_id, Image.page_num == 1)
        )
    ).scalar_one_or_none()
    cover_thumb = cas_thumb_url(cover_row) if cover_row else None
    return _g(g, cover_thumb=cover_thumb)


@router.get("/galleries/{gallery_id}/images")
async def get_gallery_images(
    gallery_id: int,
    page: int | None = Query(default=None, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await _get_or_404(db, gallery_id)
    stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id)
        .order_by(Image.page_num)
        .options(selectinload(Image.blob))
    )

    # When limit is provided, return paginated response
    if limit is not None:
        p = page or 1
        total_stmt = select(func.count()).select_from(
            select(Image.id).where(Image.gallery_id == gallery_id).subquery()
        )
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = stmt.offset((p - 1) * limit).limit(limit)
        images = (await db.execute(stmt)).scalars().all()

        return {
            "gallery_id": gallery_id,
            "images": [_i(img) for img in images],
            "total": total,
            "page": p,
            "has_next": (p * limit) < total,
        }

    # Default: return all images (backward compatible for Reader)
    images = (await db.execute(stmt)).scalars().all()
    return {"gallery_id": gallery_id, "images": [_i(img) for img in images]}


# ── Gallery update ───────────────────────────────────────────────────


class GalleryPatch(BaseModel):
    favorited: bool | None = None
    rating: int | None = None


@router.patch("/galleries/{gallery_id}")
async def update_gallery(
    gallery_id: int,
    patch: GalleryPatch,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404(db, gallery_id)
    if patch.favorited is not None:
        g.favorited = patch.favorited
    if patch.rating is not None:
        g.rating = patch.rating
    await db.commit()
    return _g(g)


@router.delete("/galleries/{gallery_id}")
async def delete_gallery(
    gallery_id: int,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a gallery, decrement blob ref counts, remove library symlinks and thumbnails.

    CAS blob files themselves are NOT deleted here — a separate GC job handles
    unreferenced blobs (ref_count == 0).
    """
    import asyncio
    import shutil
    from pathlib import Path

    g = await _get_or_404(db, gallery_id)

    # Load all images with their blobs before deleting DB records
    stmt = (
        select(Image)
        .where(Image.gallery_id == gallery_id)
        .options(selectinload(Image.blob))
    )
    images = (await db.execute(stmt)).scalars().all()

    # Collect sha256 values for cleanup after commit
    blob_sha256s = [img.blob_sha256 for img in images]

    # Decrement ref counts for all blobs
    for sha256 in blob_sha256s:
        await decrement_ref_count(sha256, db)

    # Delete from DB (CASCADE removes images, gallery_tags, read_progress)
    await db.delete(g)
    await db.commit()

    # Determine which blobs are now unreferenced (safe to delete thumbs).
    # Query after commit so ref_count reflects all decrements.
    zero_ref_sha256s: set[str] = set()
    if blob_sha256s:
        zero_ref_result = await db.execute(
            select(Blob.sha256).where(Blob.sha256.in_(blob_sha256s), Blob.ref_count <= 0)
        )
        zero_ref_sha256s = set(zero_ref_result.scalars().all())

    def _delete_filesystem() -> int:
        deleted = 0
        # Remove the entire library symlink directory for this gallery
        lib_dir = library_dir(gallery_id)
        if lib_dir.exists():
            try:
                shutil.rmtree(str(lib_dir), ignore_errors=True)
                deleted += 1
            except OSError as exc:
                logger.warning("[delete_gallery] failed to remove library dir %s: %s", lib_dir, exc)

        # Only remove thumbnail directories for blobs that are no longer referenced
        for sha256 in zero_ref_sha256s:
            td = thumb_dir(sha256)
            if td.exists():
                try:
                    shutil.rmtree(str(td), ignore_errors=True)
                    deleted += 1
                except OSError as exc:
                    logger.warning("[delete_gallery] failed to remove thumb dir %s: %s", td, exc)
        return deleted

    deleted_count = await asyncio.to_thread(_delete_filesystem)
    return {"status": "ok", "deleted_dirs": deleted_count}


# ── Read progress ────────────────────────────────────────────────────


@router.get("/galleries/{gallery_id}/progress")
async def get_progress(
    gallery_id: int,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    prog = await db.get(ReadProgress, gallery_id)
    if not prog:
        return {"gallery_id": gallery_id, "last_page": 0, "last_read_at": None}
    return {
        "gallery_id": gallery_id,
        "last_page": prog.last_page,
        "last_read_at": prog.last_read_at.isoformat() if prog.last_read_at else None,
    }


class ProgressBody(BaseModel):
    last_page: int


@router.post("/galleries/{gallery_id}/progress")
async def save_progress(
    gallery_id: int,
    body: ProgressBody,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(UTC)
    stmt = (
        pg_insert(ReadProgress)
        .values(gallery_id=gallery_id, last_page=body.last_page, last_read_at=now)
        .on_conflict_do_update(
            index_elements=["gallery_id"],
            set_={"last_page": body.last_page, "last_read_at": now},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


# ── Similar images ───────────────────────────────────────────────────


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
                        flipped ^= (1 << b)
                    signed = flipped - 0x10000 if flipped >= 0x8000 else flipped
                    neighbors.add(signed)
        result.append(neighbors)
    return result


@router.get("/images/{image_id}/similar")
async def find_similar_images(
    image_id: int,
    threshold: int = Query(default=10, ge=0, le=32),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_auth),
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
            select(Image).where(Image.id == image_id).options(selectinload(Image.blob))
        )
    ).scalar_one_or_none()
    if not img_row:
        raise HTTPException(status_code=404, detail="Image not found")
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

    if max_quarter_dist > 2 or threshold > 11:
        # For loose thresholds the neighbor sets become large (>137 per quarter);
        # fall back to full scan on phash_int with exact bit_count filter.
        stmt = sql_text("""
            SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                   b.storage, b.external_path, b.phash,
                   bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int AS distance
            FROM images i
            JOIN blobs b ON i.blob_sha256 = b.sha256
            WHERE b.phash_int IS NOT NULL
              AND i.id != :image_id
              AND bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int <= :threshold
            ORDER BY distance ASC
            LIMIT :limit
        """)
        results = (await db.execute(stmt, {
            "phash_int": phash_int_val,
            "image_id": image_id,
            "threshold": threshold,
            "limit": limit,
        })).all()
    else:
        # Phase 1: generate Hamming neighborhoods for each quarter
        neighbors = _hamming_neighbors_all(quarters, max_quarter_dist)

        # Phase 2: indexed pre-filter — OR across all four quarter columns,
        # then exact bit_count check on the surviving candidates only.
        conditions = []
        params: dict = {
            "image_id": image_id,
            "phash_int": phash_int_val,
            "threshold": threshold,
            "limit": limit,
        }
        for qi, neighbor_set in enumerate(neighbors):
            param_name = f"q{qi}_neighbors"
            conditions.append(f"b.phash_q{qi} = ANY(:{param_name})")
            params[param_name] = list(neighbor_set)

        where_prefilter = " OR ".join(conditions)

        stmt = sql_text(f"""
            SELECT i.id, i.gallery_id, i.filename, b.sha256, b.extension,
                   b.storage, b.external_path, b.phash,
                   bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int AS distance
            FROM images i
            JOIN blobs b ON i.blob_sha256 = b.sha256
            WHERE b.phash_int IS NOT NULL
              AND i.id != :image_id
              AND ({where_prefilter})
              AND bit_count((:phash_int::bigint # b.phash_int)::bit(64))::int <= :threshold
            ORDER BY distance ASC
            LIMIT :limit
        """)
        results = (await db.execute(stmt, params)).all()

    def _row_to_url(r) -> str:
        if r.storage == "external" and r.external_path:
            return r.external_path.replace("/mnt/", "/media/libraries/", 1)
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
                "phash": r.phash,
                "distance": r.distance,
            }
            for r in results
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────────


def _to_url(blob) -> str | None:
    """Convert a Blob ORM object to its nginx-served URL."""
    if not blob:
        return None
    if blob.storage == "external" and blob.external_path:
        return blob.external_path.replace("/mnt/", "/media/libraries/", 1)
    return cas_url(blob.sha256, blob.extension)


def _thumb_url(blob) -> str | None:
    """Return the 160px thumbnail URL for a blob."""
    if not blob or not blob.sha256:
        return None
    return cas_thumb_url(blob.sha256)


async def _get_or_404(db: AsyncSession, gallery_id: int) -> Gallery:
    g = await db.get(Gallery, gallery_id)
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return g


def _g(g: Gallery, cover_thumb: str | None = None) -> dict:
    return {
        "id": g.id,
        "source": g.source,
        "source_id": g.source_id,
        "title": g.title,
        "title_jpn": g.title_jpn,
        "category": g.category,
        "language": g.language,
        "pages": g.pages,
        "posted_at": g.posted_at.isoformat() if g.posted_at else None,
        "added_at": g.added_at.isoformat() if g.added_at else None,
        "rating": g.rating,
        "favorited": g.favorited,
        "uploader": g.uploader,
        "download_status": g.download_status,
        "import_mode": g.import_mode,
        "tags_array": g.tags_array or [],
        "cover_thumb": cover_thumb,
    }


def _i(img: Image) -> dict:
    blob = img.blob
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "filename": img.filename,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        "file_path": _to_url(blob),
        "thumb_path": _thumb_url(blob),
        "file_size": blob.file_size if blob else None,
        "file_hash": blob.sha256 if blob else None,
        "media_type": blob.media_type if blob else "image",
    }
