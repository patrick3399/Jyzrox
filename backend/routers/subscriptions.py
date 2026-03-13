"""Subscription management endpoints."""

import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth, require_role
from core.database import async_session
from core.redis_client import get_redis
from core.utils import detect_source
from db.models import Subscription
from plugins.registry import plugin_registry
from services.credential import get_credential

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscriptions"])

_member = require_role("member")


def _extract_source_id(url: str, source: str) -> str | None:
    """Extract artist/user ID from URL for subscription tracking."""
    parsed = urlparse(url)
    if source == "pixiv":
        m = re.search(r"/users/(\d+)", parsed.path)
        return m.group(1) if m else None
    if source == "twitter":
        parts = parsed.path.strip("/").split("/")
        return parts[0] if parts and parts[0] else None
    if source == "ehentai":
        qs = parse_qs(parsed.query)
        f_search = qs.get("f_search", [None])[0]
        if f_search:
            return f_search.strip()
        tag_match = re.match(r"/tag/(.+?)/?$", parsed.path)
        if tag_match:
            return unquote(tag_match.group(1))
        uploader_match = re.match(r"/uploader/(.+?)/?$", parsed.path)
        if uploader_match:
            return f"uploader:{unquote(uploader_match.group(1))}"
        return None
    return None


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
                "batch_total": s.batch_total,
                "batch_enqueued": s.batch_enqueued,
            }
            for s in subs
        ],
        "total": total,
    }


@router.post("/")
async def create_subscription(
    req: CreateSubscriptionRequest,
    auth: dict = Depends(_member),
):
    """Create a new subscription."""
    user_id = auth["user_id"]
    source: str | None = detect_source(req.url)
    if source == "unknown":
        source = None
    source_id = _extract_source_id(req.url, source) if source else None

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


class PreviewRequest(BaseModel):
    url: str


@router.post("/preview")
async def preview_subscription(req: PreviewRequest, auth: dict = Depends(_member)):
    """Dry-run check for a subscription URL — returns work count and samples without saving."""
    _unsupported = {"count": 0, "source": None, "source_id": None, "samples": [], "error": "unsupported"}

    source: str | None = detect_source(req.url)
    if not source or source == "unknown":
        return _unsupported

    source_id = _extract_source_id(req.url, source)
    if not source_id:
        return _unsupported

    # Check Redis cache
    redis = get_redis()
    cache_key = f"subscription:preview:{source}:{source_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    subscribable = plugin_registry.get_subscribable(source)
    if not subscribable:
        return _unsupported

    cred_raw = await get_credential(source)
    credentials: dict | None = json.loads(cred_raw) if cred_raw is not None else None

    try:
        works = await subscribable.check_new_works(source_id, None, credentials)
    except Exception as exc:
        logger.warning("preview_subscription check_new_works failed for %s/%s: %s", source, source_id, exc)
        return {
            "count": 0,
            "source": source,
            "source_id": source_id,
            "samples": [],
            "error": str(exc),
        }

    result = {
        "count": len(works),
        "source": source,
        "source_id": source_id,
        "samples": [{"url": w.url, "title": w.title} for w in works[:5]],
    }

    await redis.set(cache_key, json.dumps(result), ex=300)
    return result


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
        "batch_total": sub.batch_total,
        "batch_enqueued": sub.batch_enqueued,
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


@router.get("/{sub_id}/batch-progress")
async def get_batch_progress(sub_id: int, auth: dict = Depends(require_auth)):
    """Get real-time batch enqueue progress from Redis."""
    from core.redis_client import get_redis
    redis = get_redis()
    data = await redis.hgetall(f"subscription:batch:{sub_id}")
    if not data:
        return {"active": False}
    return {
        "active": True,
        "total": int(data.get(b"total", 0)),
        "enqueued": int(data.get(b"enqueued", 0)),
        "failed": int(data.get(b"failed", 0)),
        "started_at": (data.get(b"started_at") or b"").decode(),
    }


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
