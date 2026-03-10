"""Subscription management endpoints."""

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth
from core.database import async_session
from db.models import Subscription

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscriptions"])


def _detect_source(url: str) -> tuple[str | None, str | None]:
    """Auto-detect source and source_id from URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "pixiv" in host:
        m = re.search(r"/users/(\d+)", parsed.path)
        if m:
            return "pixiv", m.group(1)
        return "pixiv", None

    if "twitter" in host or "x.com" in host:
        parts = parsed.path.strip("/").split("/")
        if parts and parts[0]:
            return "twitter", parts[0]
        return "twitter", None

    if "e-hentai" in host or "exhentai" in host:
        return "ehentai", None

    if "nijie" in host:
        return "nijie", None

    if "fanbox" in host:
        return "fanbox", None

    return None, None


class CreateSubscriptionRequest(BaseModel):
    url: str
    name: str | None = None
    cron_expr: str | None = None
    auto_download: bool = True


class PatchSubscriptionRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    auto_download: bool | None = None
    cron_expr: str | None = None


@router.get("/")
async def list_subscriptions(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """List subscriptions for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        query = select(Subscription).where(Subscription.user_id == user_id)
        if source:
            query = query.where(Subscription.source == source)
        if enabled is not None:
            query = query.where(Subscription.enabled == enabled)
        query = query.order_by(Subscription.created_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        subs = result.scalars().all()

        count_q = select(sa_func.count(Subscription.id)).where(Subscription.user_id == user_id)
        if source:
            count_q = count_q.where(Subscription.source == source)
        if enabled is not None:
            count_q = count_q.where(Subscription.enabled == enabled)
        total = (await session.execute(count_q)).scalar() or 0

    return {
        "subscriptions": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "source": s.source,
                "source_id": s.source_id,
                "avatar_url": s.avatar_url,
                "enabled": s.enabled,
                "auto_download": s.auto_download,
                "cron_expr": s.cron_expr,
                "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
                "last_item_id": s.last_item_id,
                "last_status": s.last_status,
                "last_error": s.last_error,
                "next_check_at": s.next_check_at.isoformat() if s.next_check_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ],
        "total": total,
    }


@router.post("/")
async def create_subscription(
    req: CreateSubscriptionRequest,
    auth: dict = Depends(require_auth),
):
    """Create a new subscription."""
    user_id = auth["user_id"]
    source, source_id = _detect_source(req.url)

    if req.cron_expr:
        try:
            croniter(req.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")

    async with async_session() as session:
        stmt = pg_insert(Subscription).values(
            user_id=user_id,
            url=req.url,
            name=req.name,
            source=source,
            source_id=source_id,
            auto_download=req.auto_download,
            cron_expr=req.cron_expr or "0 */2 * * *",
        ).on_conflict_do_update(
            constraint="uq_subscription_user_url",
            set_={
                "name": req.name,
                "auto_download": req.auto_download,
                "cron_expr": req.cron_expr or "0 */2 * * *",
                "enabled": True,
            },
        ).returning(Subscription.id)

        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()

    return {"status": "ok", "id": row.id if row else None, "source": source}


@router.get("/{sub_id}")
async def get_subscription(
    sub_id: int,
    auth: dict = Depends(require_auth),
):
    """Get subscription detail."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
        )).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    return {
        "id": sub.id,
        "name": sub.name,
        "url": sub.url,
        "source": sub.source,
        "source_id": sub.source_id,
        "avatar_url": sub.avatar_url,
        "enabled": sub.enabled,
        "auto_download": sub.auto_download,
        "cron_expr": sub.cron_expr,
        "last_checked_at": sub.last_checked_at.isoformat() if sub.last_checked_at else None,
        "last_item_id": sub.last_item_id,
        "last_status": sub.last_status,
        "last_error": sub.last_error,
        "next_check_at": sub.next_check_at.isoformat() if sub.next_check_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }


@router.patch("/{sub_id}")
async def update_subscription(
    sub_id: int,
    req: PatchSubscriptionRequest,
    auth: dict = Depends(require_auth),
):
    """Update a subscription."""
    user_id = auth["user_id"]

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.enabled is not None:
        updates["enabled"] = req.enabled
    if req.auto_download is not None:
        updates["auto_download"] = req.auto_download
    if req.cron_expr is not None:
        try:
            croniter(req.cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")
        updates["cron_expr"] = req.cron_expr

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with async_session() as session:
        result = await session.execute(
            update(Subscription).where(
                Subscription.id == sub_id,
                Subscription.user_id == user_id,
            ).values(**updates).returning(Subscription.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "ok"}


@router.delete("/{sub_id}")
async def delete_subscription(
    sub_id: int,
    auth: dict = Depends(require_auth),
):
    """Delete a subscription."""
    user_id = auth["user_id"]
    async with async_session() as session:
        result = await session.execute(
            delete(Subscription).where(
                Subscription.id == sub_id,
                Subscription.user_id == user_id,
            ).returning(Subscription.id)
        )
        deleted = result.fetchone()
        await session.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "ok"}


@router.post("/{sub_id}/check")
async def check_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Trigger immediate check for a subscription."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
        )).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        arq = request.app.state.arq
        await arq.enqueue_job("check_single_subscription", sub_id)
    except Exception as exc:
        logger.error("Failed to enqueue check_single_subscription: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id}
