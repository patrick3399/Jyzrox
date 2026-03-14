"""Artist following management endpoints — backed by subscriptions table."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth
from core.database import async_session
from core.errors import api_error, parse_accept_language
from db.models import Subscription

logger = logging.getLogger(__name__)
router = APIRouter(tags=["artists"])


def _artist_url(source: str, artist_id: str) -> str:
    """Generate a canonical URL for an artist."""
    from plugins.builtin.gallery_dl._sites import get_site_config
    cfg = get_site_config(source)
    if cfg.artist_url_tpl:
        return cfg.artist_url_tpl.format(artist_id)
    if cfg.domain:
        return f"https://{cfg.domain}/{artist_id}"
    return f"https://{source}/{artist_id}"


class FollowArtistRequest(BaseModel):
    source: str
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
        query = select(Subscription).where(Subscription.user_id == user_id)
        if source:
            query = query.where(Subscription.source == source)
        query = query.order_by(Subscription.created_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        subs = result.scalars().all()

        count_q = select(sa_func.count(Subscription.id)).where(Subscription.user_id == user_id)
        if source:
            count_q = count_q.where(Subscription.source == source)
        total = (await session.execute(count_q)).scalar() or 0

    return {
        "artists": [
            {
                "id": s.id,
                "source": s.source,
                "artist_id": s.source_id,
                "artist_name": s.name,
                "artist_avatar": s.avatar_url,
                "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
                "last_illust_id": s.last_item_id,
                "auto_download": s.auto_download,
                "added_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ],
        "total": total,
    }


@router.post("/follow")
async def follow_artist(
    req: FollowArtistRequest,
    auth: dict = Depends(require_auth),
    request: Request = None,
):
    """Follow an artist (creates a subscription)."""
    user_id = auth["user_id"]
    url = _artist_url(req.source, req.artist_id)

    async with async_session() as session:
        stmt = pg_insert(Subscription).values(
            user_id=user_id,
            url=url,
            name=req.artist_name,
            source=req.source,
            source_id=req.artist_id,
            avatar_url=req.artist_avatar,
            auto_download=req.auto_download,
        ).on_conflict_do_update(
            constraint="uq_subscription_user_url",
            set_={
                "name": req.artist_name,
                "avatar_url": req.artist_avatar,
                "auto_download": req.auto_download,
                "enabled": True,
            },
        ).returning(Subscription.id)

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
    """Unfollow an artist (deletes the subscription)."""
    user_id = auth["user_id"]
    locale = parse_accept_language(request.headers.get("accept-language")) if request else "en"

    async with async_session() as session:
        result = await session.execute(
            delete(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.source == source,
                Subscription.source_id == artist_id,
            ).returning(Subscription.id)
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
        updates["name"] = req.artist_name
    if req.artist_avatar is not None:
        updates["avatar_url"] = req.artist_avatar

    if not updates:
        raise api_error(400, "invalid_request", locale)

    async with async_session() as session:
        result = await session.execute(
            update(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.source == source,
                Subscription.source_id == artist_id,
            ).values(**updates).returning(Subscription.id)
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
    try:
        arq = request.app.state.arq
        await arq.enqueue_job("check_followed_artists", auth["user_id"])
    except Exception as e:
        logger.error("Failed to enqueue check_followed_artists: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "queued"}
