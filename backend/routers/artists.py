"""Artist following management endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth
from core.database import async_session
from core.errors import api_error, parse_accept_language
from db.models import FollowedArtist

logger = logging.getLogger(__name__)
router = APIRouter(tags=["artists"])


class FollowArtistRequest(BaseModel):
    source: str  # "pixiv", "ehentai"
    artist_id: str
    artist_name: str | None = None
    artist_avatar: str | None = None
    auto_download: bool = False


class PatchFollowRequest(BaseModel):
    auto_download: bool | None = None
    artist_name: str | None = None
    artist_avatar: str | None = None


@router.get("/followed")
async def list_followed(
    source: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """List followed artists for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        query = select(FollowedArtist).where(FollowedArtist.user_id == user_id)
        if source:
            query = query.where(FollowedArtist.source == source)
        query = query.order_by(FollowedArtist.added_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        artists = result.scalars().all()

        # Get total count
        count_q = select(sa_func.count(FollowedArtist.id)).where(FollowedArtist.user_id == user_id)
        if source:
            count_q = count_q.where(FollowedArtist.source == source)
        total = (await session.execute(count_q)).scalar() or 0

    return {
        "artists": [
            {
                "id": a.id,
                "source": a.source,
                "artist_id": a.artist_id,
                "artist_name": a.artist_name,
                "artist_avatar": a.artist_avatar,
                "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None,
                "last_illust_id": a.last_illust_id,
                "auto_download": a.auto_download,
                "added_at": a.added_at.isoformat() if a.added_at else None,
            }
            for a in artists
        ],
        "total": total,
    }


@router.post("/follow")
async def follow_artist(
    req: FollowArtistRequest,
    auth: dict = Depends(require_auth),
    request: Request = None,
):
    """Follow an artist."""
    user_id = auth["user_id"]
    locale = parse_accept_language(request.headers.get("accept-language")) if request else "en"

    async with async_session() as session:
        stmt = pg_insert(FollowedArtist).values(
            user_id=user_id,
            source=req.source,
            artist_id=req.artist_id,
            artist_name=req.artist_name,
            artist_avatar=req.artist_avatar,
            auto_download=req.auto_download,
        ).on_conflict_do_update(
            constraint="uq_followed_artist",
            set_={
                "artist_name": req.artist_name,
                "artist_avatar": req.artist_avatar,
                "auto_download": req.auto_download,
            },
        ).returning(FollowedArtist.id)

        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()

    return {"status": "ok", "id": row.id if row else None}


@router.delete("/follow/{artist_id}")
async def unfollow_artist(
    artist_id: str,
    source: str = Query(default="pixiv"),
    auth: dict = Depends(require_auth),
    request: Request = None,
):
    """Unfollow an artist."""
    user_id = auth["user_id"]
    locale = parse_accept_language(request.headers.get("accept-language")) if request else "en"

    async with async_session() as session:
        result = await session.execute(
            delete(FollowedArtist).where(
                FollowedArtist.user_id == user_id,
                FollowedArtist.source == source,
                FollowedArtist.artist_id == artist_id,
            ).returning(FollowedArtist.id)
        )
        deleted = result.fetchone()
        await session.commit()

    if not deleted:
        raise api_error(404, "not_found", locale)
    return {"status": "ok"}


@router.patch("/follow/{artist_id}")
async def patch_follow(
    artist_id: str,
    req: PatchFollowRequest,
    source: str = Query(default="pixiv"),
    auth: dict = Depends(require_auth),
    request: Request = None,
):
    """Update follow settings (auto_download, name, avatar)."""
    user_id = auth["user_id"]
    locale = parse_accept_language(request.headers.get("accept-language")) if request else "en"

    updates = {}
    if req.auto_download is not None:
        updates["auto_download"] = req.auto_download
    if req.artist_name is not None:
        updates["artist_name"] = req.artist_name
    if req.artist_avatar is not None:
        updates["artist_avatar"] = req.artist_avatar

    if not updates:
        raise api_error(400, "invalid_request", locale)

    async with async_session() as session:
        result = await session.execute(
            update(FollowedArtist).where(
                FollowedArtist.user_id == user_id,
                FollowedArtist.source == source,
                FollowedArtist.artist_id == artist_id,
            ).values(**updates).returning(FollowedArtist.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise api_error(404, "not_found", locale)
    return {"status": "ok"}


@router.post("/check-updates")
async def check_updates(
    auth: dict = Depends(require_auth),
    request: Request = None,
):
    """Manually trigger update check for followed artists."""
    # Enqueue the check job via ARQ using the app-level pool
    try:
        arq = request.app.state.arq
        await arq.enqueue_job("check_followed_artists", auth["user_id"])
    except Exception as e:
        logger.error("Failed to enqueue check_followed_artists: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "queued"}
