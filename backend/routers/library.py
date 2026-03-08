"""Local library CRUD — queries galleries/images tables via GIN index."""

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from db.models import Gallery, Image, ReadProgress

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
    _: dict = Depends(require_auth),
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
        return {
            "galleries": [_g(g) for g in rows],
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
        return {"total": total, "page": page, "galleries": [_g(g) for g in galleries]}


@router.get("/galleries/{gallery_id}")
async def get_gallery(
    gallery_id: int,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404(db, gallery_id)
    return _g(g)


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


# ── Helpers ──────────────────────────────────────────────────────────


async def _get_or_404(db: AsyncSession, gallery_id: int) -> Gallery:
    g = await db.get(Gallery, gallery_id)
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return g


def _g(g: Gallery) -> dict:
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
    }


def _i(img: Image) -> dict:
    return {
        "id": img.id,
        "gallery_id": img.gallery_id,
        "page_num": img.page_num,
        "filename": img.filename,
        "width": img.width,
        "height": img.height,
        "file_path": img.file_path,
        "thumb_path": img.thumb_path,
        "file_size": img.file_size,
        "file_hash": img.file_hash,
    }
