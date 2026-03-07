"""Local library CRUD — queries galleries/images tables via GIN index."""

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, not_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from db.models import Gallery, Image, ReadProgress

logger = logging.getLogger(__name__)
router = APIRouter(tags=["library"])


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
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Search local library.
    Tag filtering uses tags_array GIN index for performance:
      tags=character:rem&tags=general:blue_hair → AND
      exclude_tags=general:sketch              → NOT
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

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    sort_col = {"added_at": Gallery.added_at, "rating": Gallery.rating, "pages": Gallery.pages}[sort]
    stmt = stmt.order_by(desc(sort_col)).offset(page * limit).limit(limit)

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
    now = datetime.now(timezone.utc)
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
        "id":              g.id,
        "source":          g.source,
        "source_id":       g.source_id,
        "title":           g.title,
        "title_jpn":       g.title_jpn,
        "category":        g.category,
        "language":        g.language,
        "pages":           g.pages,
        "posted_at":       g.posted_at.isoformat() if g.posted_at else None,
        "added_at":        g.added_at.isoformat() if g.added_at else None,
        "rating":          g.rating,
        "favorited":       g.favorited,
        "uploader":        g.uploader,
        "download_status": g.download_status,
        "tags_array":      g.tags_array or [],
    }


def _i(img: Image) -> dict:
    return {
        "id":         img.id,
        "gallery_id": img.gallery_id,
        "page_num":   img.page_num,
        "filename":   img.filename,
        "width":      img.width,
        "height":     img.height,
        "file_path":  img.file_path,
        "thumb_path": img.thumb_path,
        "file_size":  img.file_size,
        "file_hash":  img.file_hash,
    }
