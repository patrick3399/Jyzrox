"""Subscription check, stop, pause, resume and backfill endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update

import core.queue
import core.redis_client
from core.auth import require_auth, require_role
from core.database import async_session
from db.models import DownloadJob, Subscription
from services.download_stop import StopNotAllowed, request_stop
from services.subscription_pause import pause_subscription, resume_subscription

logger = logging.getLogger(__name__)
router = APIRouter()

_member = require_role("member")


@router.post("/{sub_id}/check")
async def check_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Trigger immediate check for a subscription."""
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if sub.paused_at is not None:
        raise HTTPException(status_code=409, detail="Subscription is paused")

    try:
        await core.queue.enqueue("check_single_subscription", _timeout=600, sub_id=sub_id)
    except Exception as exc:
        logger.error("Failed to enqueue check_single_subscription: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id}


@router.post("/{sub_id}/stop")
async def stop_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(_member),
):
    """Stop every active job of a subscription and keep what they fetched.

    Unlike delete (which cancels and discards), a stop finishes each job through
    the worker's keep path and moves the subscription boundary, so later checks
    only fetch newer posts. Jobs that already finished are skipped.
    """
    user_id = auth["user_id"]
    stopped = 0
    failed = 0
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Only the ids are listed up front. request_stop decides per job from
        # the database, so a job that finished (or started) since this listing
        # is handled correctly, and a failure that rolls the session back
        # cannot leave later iterations holding expired instances.
        job_ids = (
            (
                await session.execute(
                    select(DownloadJob.id)
                    .where(
                        DownloadJob.subscription_id == sub_id,
                        DownloadJob.status.in_(["queued", "running", "paused"]),
                    )
                    .order_by(DownloadJob.created_at)
                )
            )
            .scalars()
            .all()
        )
        for job_id in job_ids:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                continue
            try:
                await request_stop(session, job)
            except StopNotAllowed:
                continue  # finished since the listing
            except Exception as exc:
                # One failed enqueue must not leave the remaining jobs running.
                logger.error("[subscription] stop failed for job %s of sub %d: %s", job_id, sub_id, exc)
                failed += 1
                continue
            stopped += 1

        # Stop wins over pause: a stopped subscription is no longer paused.
        await session.execute(
            update(Subscription)
            .where(Subscription.id == sub_id)
            .values(paused_at=None, paused_reason=None, paused_until=None)
        )
        await session.commit()

    if failed and not stopped:
        raise HTTPException(status_code=503, detail="Failed to stop subscription jobs")
    return {"status": "ok", "stopped": stopped}


@router.post("/{sub_id}/pause")
async def pause_subscription_route(sub_id: int, auth: dict = Depends(_member)):
    """Pause a subscription and every queued/running job it owns."""
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == auth["user_id"])
            )
        ).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        out = await pause_subscription(session, sub_id, reason="manual")
    await core.redis_client.publish_job_event(
        {
            "type": "subscription_checked",
            "sub_id": sub_id,
            "status": "paused",
            "job_id": None,
            "user_id": auth["user_id"],
        }
    )
    return {"status": "ok", "paused_jobs": out["paused_jobs"]}


@router.post("/{sub_id}/resume")
async def resume_subscription_route(sub_id: int, auth: dict = Depends(_member)):
    """Resume a paused subscription, re-queueing its paused jobs in ticket order."""
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == auth["user_id"])
            )
        ).scalar_one_or_none()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        try:
            out = await resume_subscription(session, sub_id)
        except RuntimeError:
            raise HTTPException(status_code=503, detail="Failed to re-enqueue some jobs; resume again")
    await core.redis_client.publish_job_event(
        {
            "type": "subscription_checked",
            "sub_id": sub_id,
            "status": "resumed",
            "job_id": None,
            "user_id": auth["user_id"],
        }
    )
    return {"status": "ok", "resumed_jobs": out["resumed_jobs"]}


@router.post("/{sub_id}/backfill")
async def backfill_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(_member),
):
    """Trigger a force re-scan for a subscription.

    Bypasses both the incremental ``date-after`` filter and gallery-dl's
    archive so the current remote timeline is downloaded again. Importer-side
    de-duplication keeps existing local rows and social ordering preserves
    already-downloaded items even if their remote posts have disappeared.
    """
    user_id = auth["user_id"]
    async with async_session() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
            )
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if sub.paused_at is not None:
        raise HTTPException(status_code=409, detail="Subscription is paused")

    try:
        await core.queue.enqueue("check_single_subscription", _timeout=600, sub_id=sub_id, force_full_scan=True)
    except Exception as exc:
        logger.error("Failed to enqueue force re-scan for sub %d: %s", sub_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "queued", "subscription_id": sub_id, "mode": "force_rescan"}
