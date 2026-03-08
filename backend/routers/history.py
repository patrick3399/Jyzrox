"""Browse history endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth
from core.database import async_session
from db.models import BrowseHistory

logger = logging.getLogger(__name__)
router = APIRouter(tags=["history"])


class HistoryRecord(BaseModel):
    source: str
    source_id: str
    title: str | None = None
    thumb: str | None = None
    gid: int | None = None
    token: str | None = None


@router.get("/")
async def list_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """List browse history for the current user, newest first."""
    user_id = auth["user_id"]
    async with async_session() as session:
        rows = (
            await session.execute(
                select(BrowseHistory)
                .where(BrowseHistory.user_id == user_id)
                .order_by(desc(BrowseHistory.viewed_at))
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    return {
        "items": [_h(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.post("/", status_code=201)
async def record_history(
    body: HistoryRecord,
    auth: dict = Depends(require_auth),
):
    """Record a gallery view. Upserts by (user_id, source, source_id)."""
    user_id = auth["user_id"]
    now = datetime.now(UTC)
    stmt = (
        pg_insert(BrowseHistory)
        .values(
            user_id=user_id,
            source=body.source,
            source_id=body.source_id,
            title=body.title,
            thumb=body.thumb,
            gid=body.gid,
            token=body.token,
            viewed_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "source", "source_id"],
            set_={
                "title": body.title,
                "thumb": body.thumb,
                "gid": body.gid,
                "token": body.token,
                "viewed_at": now,
            },
        )
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()
    return {"status": "ok"}


@router.delete("/")
async def clear_history(
    auth: dict = Depends(require_auth),
):
    """Clear all browse history for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        result = await session.execute(
            delete(BrowseHistory).where(BrowseHistory.user_id == user_id)
        )
        await session.commit()
    return {"status": "ok", "deleted": result.rowcount}


@router.delete("/{entry_id}")
async def delete_history_entry(
    entry_id: int,
    auth: dict = Depends(require_auth),
):
    """Delete a single browse history entry."""
    user_id = auth["user_id"]
    async with async_session() as session:
        row = (
            await session.execute(
                select(BrowseHistory).where(
                    BrowseHistory.id == entry_id,
                    BrowseHistory.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="History entry not found")
        await session.delete(row)
        await session.commit()
    return {"status": "ok"}


# ── Helper ────────────────────────────────────────────────────────────


def _h(r: BrowseHistory) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "source_id": r.source_id,
        "title": r.title,
        "thumb": r.thumb,
        "gid": r.gid,
        "token": r.token,
        "viewed_at": r.viewed_at.isoformat() if r.viewed_at else None,
    }
