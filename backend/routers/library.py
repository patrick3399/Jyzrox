"""Local library CRUD — queries galleries/images tables via GIN index."""

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ARRAY, Text, and_, cast, desc, func, not_, or_, select
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from db.models import BlockedTag, Gallery, Image, ReadProgress

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
            cover_stmt = select(Image.gallery_id, Image.thumb_path).where(
                Image.gallery_id.in_(gallery_ids), Image.page_num == 1
            )
            cover_rows = (await db.execute(cover_stmt)).all()
            cover_map = {r.gallery_id: _to_url(r.thumb_path, "/data/thumbs/", "/media/thumbs/") for r in cover_rows}
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
            cover_stmt = select(Image.gallery_id, Image.thumb_path).where(
                Image.gallery_id.in_(gallery_ids), Image.page_num == 1
            )
            cover_rows = (await db.execute(cover_stmt)).all()
            cover_map = {r.gallery_id: _to_url(r.thumb_path, "/data/thumbs/", "/media/thumbs/") for r in cover_rows}
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
            select(Image.thumb_path).where(Image.gallery_id == gallery_id, Image.page_num == 1)
        )
    ).scalar_one_or_none()
    cover_thumb = _to_url(cover_row, "/data/thumbs/", "/media/thumbs/")
    return _g(g, cover_thumb=cover_thumb)


@router.get("/galleries/{gallery_id}/images")
async def get_gallery_images(
    gallery_id: int,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await _get_or_404(db, gallery_id)
    stmt = select(Image).where(Image.gallery_id == gallery_id).order_by(Image.page_num)
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
    """Delete a gallery and its associated files (images + thumbnails)."""
    import asyncio
    from pathlib import Path

    from core.config import settings as app_settings

    g = await _get_or_404(db, gallery_id)

    # Collect file paths before deleting DB records
    stmt = select(Image.file_path, Image.thumb_path).where(Image.gallery_id == gallery_id)
    image_rows = (await db.execute(stmt)).all()

    # Delete from DB (cascades to images, gallery_tags, read_progress)
    await db.delete(g)
    await db.commit()

    allowed_gallery = Path(app_settings.data_gallery_path).resolve()
    allowed_thumbs = Path(app_settings.data_thumbs_path).resolve()

    def _is_safe_path(p: Path) -> bool:
        """Return True only if path is within an allowed base directory."""
        try:
            resolved = p.resolve()
            return resolved.is_relative_to(allowed_gallery) or resolved.is_relative_to(allowed_thumbs)
        except (OSError, ValueError):
            return False

    def _delete_files() -> int:
        deleted = 0
        for row in image_rows:
            for path_str in (row.file_path, row.thumb_path):
                if path_str:
                    p = Path(path_str)
                    if not _is_safe_path(p):
                        logger.warning("[delete_gallery] skipping unsafe path: %s", path_str)
                        continue
                    try:
                        if p.is_file():
                            p.unlink()
                            deleted += 1
                    except OSError:
                        pass
            # Clean up thumb directory (hash-based dir like /data/thumbs/ab/abcdef.../)
            if row.thumb_path:
                thumb_dir = Path(row.thumb_path).parent
                if _is_safe_path(thumb_dir):
                    try:
                        if thumb_dir.is_dir() and not any(thumb_dir.iterdir()):
                            thumb_dir.rmdir()
                    except OSError:
                        pass

        # Try to remove gallery directory if empty
        if image_rows and image_rows[0].file_path:
            gallery_dir = Path(image_rows[0].file_path).parent
            if _is_safe_path(gallery_dir):
                try:
                    if gallery_dir.is_dir() and not any(gallery_dir.iterdir()):
                        gallery_dir.rmdir()
                except OSError:
                    pass

        return deleted

    deleted_files = await asyncio.to_thread(_delete_files)
    return {"status": "ok", "deleted_files": deleted_files}


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


@router.get("/images/{image_id}/similar")
async def find_similar_images(
    image_id: int,
    threshold: int = Query(default=10, ge=0, le=32),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Find visually similar images by perceptual hash Hamming distance.

    Uses PostgreSQL 15 bit_count() on the XOR of two 64-bit pHash values
    (stored as hex strings) to compute Hamming distance in pure SQL.
    Threshold 0 = exact match, 10 = visually similar (recommended default),
    32 = very loose match.
    """
    img = await db.get(Image, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    if not img.phash:
        raise HTTPException(status_code=400, detail="Image has no perceptual hash")

    stmt = sql_text("""
        SELECT id, gallery_id, filename, file_path, thumb_path, phash,
               bit_count(
                   ('x' || lpad(:phash, 16, '0'))::bit(64)
                   #
                   ('x' || lpad(phash, 16, '0'))::bit(64)
               )::int AS distance
        FROM images
        WHERE phash IS NOT NULL
          AND id != :image_id
          AND bit_count(
                  ('x' || lpad(:phash, 16, '0'))::bit(64)
                  #
                  ('x' || lpad(phash, 16, '0'))::bit(64)
              )::int <= :threshold
        ORDER BY distance ASC
        LIMIT :limit
    """)

    results = (
        await db.execute(
            stmt,
            {
                "phash": img.phash,
                "image_id": image_id,
                "threshold": threshold,
                "limit": limit,
            },
        )
    ).all()

    return {
        "image_id": image_id,
        "phash": img.phash,
        "similar": [
            {
                "id": r.id,
                "gallery_id": r.gallery_id,
                "filename": r.filename,
                "file_path": _to_url(r.file_path, "/data/gallery/", "/media/gallery/"),
                "thumb_path": _to_url(r.thumb_path, "/data/thumbs/", "/media/thumbs/"),
                "phash": r.phash,
                "distance": r.distance,
            }
            for r in results
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────────


def _to_url(path: str | None, fs_prefix: str, url_prefix: str) -> str | None:
    if not path:
        return None
    return path.replace(fs_prefix, url_prefix, 1)


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
        "tags_array": g.tags_array or [],
        "cover_thumb": cover_thumb,
    }


def _i(img: Image) -> dict:
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "filename": img.filename,
        "width": img.width,
        "height": img.height,
        "file_path": _to_url(img.file_path, "/data/gallery/", "/media/gallery/"),
        "thumb_path": _to_url(img.thumb_path, "/data/thumbs/", "/media/thumbs/"),
        "file_size": img.file_size,
        "file_hash": img.file_hash,
    }
