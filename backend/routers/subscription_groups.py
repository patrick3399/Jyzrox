"""Subscription group management endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select, update

import core.queue
from core.auth import require_role
from core.database import async_session
from core.utils import validate_cron
from db.models import Subscription, SubscriptionGroup

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscription-groups"])

_admin = require_role("admin")


# Group concurrency is passed straight to asyncio.Semaphore() in the worker, so
# it must be a sane positive bound: <=0 stalls/raises and unbounded values give
# no real cap (edge case #31).
_CONCURRENCY = Field(default=2, ge=1, le=20)


class CreateGroupRequest(BaseModel):
    name: str
    schedule: str = "0 */6 * * *"
    concurrency: int = _CONCURRENCY
    priority: int = 5


class UpdateGroupRequest(BaseModel):
    name: str | None = None
    schedule: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=20)
    priority: int | None = None
    enabled: bool | None = None


def _serialize_group(g, sub_count: int = 0) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "schedule": g.schedule,
        "concurrency": g.concurrency,
        "enabled": g.enabled,
        "priority": g.priority,
        "is_system": g.is_system,
        "status": g.status,
        "last_run_at": g.last_run_at.isoformat() if g.last_run_at else None,
        "last_completed_at": g.last_completed_at.isoformat() if g.last_completed_at else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        "sub_count": sub_count,
    }


@router.get("/")
async def list_groups(auth: dict = Depends(_admin)):
    """List all subscription groups with subscription count."""
    async with async_session() as session:
        # Subquery for subscription count per group
        count_sq = (
            select(Subscription.group_id, sa_func.count(Subscription.id).label("cnt"))
            .where(Subscription.group_id.isnot(None))
            .group_by(Subscription.group_id)
            .subquery()
        )
        stmt = (
            select(SubscriptionGroup, sa_func.coalesce(count_sq.c.cnt, 0).label("sub_count"))
            .outerjoin(count_sq, SubscriptionGroup.id == count_sq.c.group_id)
            .order_by(SubscriptionGroup.priority.desc(), SubscriptionGroup.id)
        )
        rows = (await session.execute(stmt)).all()

    return {
        "groups": [_serialize_group(row[0], row[1]) for row in rows],
    }


@router.post("/")
async def create_group(req: CreateGroupRequest, auth: dict = Depends(_admin)):
    """Create a new subscription group."""
    validate_cron(req.schedule)

    async with async_session() as session:
        group = SubscriptionGroup(
            name=req.name,
            schedule=req.schedule,
            concurrency=req.concurrency,
            priority=req.priority,
        )
        session.add(group)
        await session.flush()
        group_id = group.id
        await session.commit()

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_GROUP_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="subscription_group",
        resource_id=group_id,
    )
    return {"status": "ok", "id": group_id}


@router.get("/{group_id}")
async def get_group(group_id: int, auth: dict = Depends(_admin)):
    """Get group detail with subscription count."""
    async with async_session() as session:
        group = await session.get(SubscriptionGroup, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        sub_count = (
            await session.execute(select(sa_func.count(Subscription.id)).where(Subscription.group_id == group_id))
        ).scalar() or 0

    return _serialize_group(group, sub_count)


@router.patch("/{group_id}")
async def update_group(group_id: int, req: UpdateGroupRequest, auth: dict = Depends(_admin)):
    """Update a subscription group. Cannot modify is_system flag."""
    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.schedule is not None:
        validate_cron(req.schedule)
        updates["schedule"] = req.schedule
    if req.concurrency is not None:
        updates["concurrency"] = req.concurrency
    if req.priority is not None:
        updates["priority"] = req.priority
    if req.enabled is not None:
        updates["enabled"] = req.enabled

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.now(UTC)

    async with async_session() as session:
        result = await session.execute(
            update(SubscriptionGroup)
            .where(SubscriptionGroup.id == group_id)
            .values(**updates)
            .returning(SubscriptionGroup.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Group not found")

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_GROUP_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="subscription_group",
        resource_id=group_id,
    )
    return {"status": "ok"}


@router.delete("/{group_id}")
async def delete_group(group_id: int, auth: dict = Depends(_admin)):
    """Delete a subscription group. System groups cannot be deleted."""
    async with async_session() as session:
        group = await session.get(SubscriptionGroup, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if group.is_system:
            raise HTTPException(status_code=400, detail="Cannot delete system group")
        await session.delete(group)
        await session.commit()

    return {"status": "ok"}


@router.post("/{group_id}/run")
async def run_group(group_id: int, request: Request, auth: dict = Depends(_admin)):
    """Run Now — enqueue check_subscription_group job."""
    async with async_session() as session:
        group = await session.get(SubscriptionGroup, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

    try:
        # Explicit _timeout: SAQ's default Job.timeout is 10s. No start_jitter —
        # a user pressing Run Now expects it to start immediately.
        from worker.constants import GROUP_JOB_TIMEOUT

        await core.queue.enqueue("check_subscription_group", _timeout=GROUP_JOB_TIMEOUT, group_id=group_id)
    except Exception as exc:
        logger.error("Failed to enqueue check_subscription_group: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "group_id": group_id}


@router.post("/{group_id}/pause")
async def pause_group(group_id: int, auth: dict = Depends(_admin)):
    """Pause a subscription group."""
    async with async_session() as session:
        result = await session.execute(
            update(SubscriptionGroup)
            .where(SubscriptionGroup.id == group_id)
            .values(status="paused", updated_at=datetime.now(UTC))
            .returning(SubscriptionGroup.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "ok"}


@router.post("/{group_id}/resume")
async def resume_group(group_id: int, auth: dict = Depends(_admin)):
    """Resume a paused subscription group."""
    async with async_session() as session:
        result = await session.execute(
            update(SubscriptionGroup)
            .where(SubscriptionGroup.id == group_id, SubscriptionGroup.status == "paused")
            .values(status="idle", updated_at=datetime.now(UTC))
            .returning(SubscriptionGroup.id)
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Group not found or not paused")
    return {"status": "ok"}
