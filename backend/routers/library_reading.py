"""Library split from routers/library.py (library_reading)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from db.models import (
    Gallery,
    GalleryTag,
    Image,
    ReadEvent,
    ReadProgress,
    Tag,
)
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source

_member = require_role("member")
router = APIRouter()


class ReadEventBody(BaseModel):
    gallery_id: int
    page_num: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


@router.post("/read-events", status_code=201)
async def create_read_event(
    body: ReadEventBody,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == body.gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")
    image_id = (
        await db.execute(
            select(Image.id).where(
                Image.gallery_id == gallery.id,
                Image.page_num == body.page_num,
                Image.visibility == "active",
            )
        )
    ).scalar_one_or_none()
    db.add(
        ReadEvent(
            user_id=auth["user_id"],
            gallery_id=gallery.id,
            image_id=image_id,
            page_num=body.page_num,
            duration_ms=body.duration_ms,
        )
    )
    await db.commit()
    return {"status": "recorded"}


@router.get("/stats")
async def get_reading_stats(
    days: int = Query(default=30, ge=1, le=365),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(UTC) - timedelta(days=days)
    trend_rows = (
        await db.execute(
            select(
                func.date(ReadEvent.occurred_at),
                func.count(ReadEvent.id),
                func.count(func.distinct(ReadEvent.gallery_id)),
            )
            .where(ReadEvent.user_id == auth["user_id"], ReadEvent.occurred_at >= cutoff)
            .group_by(func.date(ReadEvent.occurred_at))
            .order_by(func.date(ReadEvent.occurred_at))
        )
    ).all()
    tag_rows = (
        await db.execute(
            select(Tag.namespace, Tag.name, func.count(ReadEvent.id).label("reads"))
            .join(GalleryTag, GalleryTag.tag_id == Tag.id)
            .join(ReadEvent, ReadEvent.gallery_id == GalleryTag.gallery_id)
            .join(Gallery, Gallery.id == ReadEvent.gallery_id)
            .where(
                ReadEvent.user_id == auth["user_id"],
                ReadEvent.occurred_at >= cutoff,
                gallery_access_filter(auth),
            )
            .group_by(Tag.id, Tag.namespace, Tag.name)
            .order_by(desc("reads"))
            .limit(12)
        )
    ).all()
    unfinished_rows = (
        await db.execute(
            select(ReadProgress, Gallery)
            .join(Gallery, Gallery.id == ReadProgress.gallery_id)
            .where(
                ReadProgress.user_id == auth["user_id"],
                ReadProgress.last_page > 0,
                ReadProgress.last_page < func.coalesce(Gallery.pages, 0),
                gallery_access_filter(auth),
            )
            .order_by(ReadProgress.last_read_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "days": days,
        "trend": [
            {"date": str(date), "events": events, "galleries": galleries} for date, events, galleries in trend_rows
        ],
        "top_tags": [{"namespace": namespace, "name": name, "reads": reads} for namespace, name, reads in tag_rows],
        "unfinished": [
            {
                "gallery_id": gallery.id,
                "source": gallery.source,
                "source_id": gallery.source_id,
                "title": gallery.title,
                "last_page": progress.last_page,
                "pages": gallery.pages,
                "last_read_at": progress.last_read_at.isoformat(),
            }
            for progress, gallery in unfinished_rows
        ],
    }


@router.get("/galleries/{source}/{source_id}/progress")
async def get_progress(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    prog = await db.get(ReadProgress, (auth["user_id"], gallery_id))
    if not prog:
        return {"gallery_id": gallery_id, "last_page": 0, "last_image_id": None, "last_read_at": None}
    return {
        "gallery_id": gallery_id,
        "last_page": prog.last_page,
        "last_image_id": prog.last_image_id,
        "last_read_at": prog.last_read_at.isoformat() if prog.last_read_at else None,
    }


class ProgressBody(BaseModel):
    last_page: int = Field(ge=0)


@router.post("/galleries/{source}/{source_id}/progress")
async def save_progress(
    source: str,
    source_id: str,
    body: ProgressBody,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    now = datetime.now(UTC)
    previous = await db.get(ReadProgress, (auth["user_id"], gallery_id))
    last_image_id = (
        await db.execute(
            select(Image.id).where(
                Image.gallery_id == gallery_id,
                Image.page_num == body.last_page,
                Image.visibility == "active",
            )
        )
    ).scalar_one_or_none()
    stmt = (
        pg_insert(ReadProgress)
        .values(
            user_id=auth["user_id"],
            gallery_id=gallery_id,
            last_page=body.last_page,
            last_image_id=last_image_id,
            last_read_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "gallery_id"],
            set_={"last_page": body.last_page, "last_image_id": last_image_id, "last_read_at": now},
        )
    )
    await db.execute(stmt)
    if previous is None or previous.last_page != body.last_page:
        db.add(
            ReadEvent(
                user_id=auth["user_id"],
                gallery_id=gallery_id,
                image_id=last_image_id,
                page_num=body.last_page,
            )
        )
    await db.commit()
    return {"status": "ok"}
