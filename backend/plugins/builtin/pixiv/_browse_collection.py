"""Pixiv browse routes: user collection sync and subscription."""

import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

import core.queue
from core.auth import require_auth, require_role
from core.config import settings
from core.database import async_session
from core.events import EventType, emit_safe
from core.utils import normalize_download_url
from db.models import DownloadJob, Gallery, GallerySourceItem, Subscription
from plugins.builtin.pixiv._browse_common import _browse_router
from services.download_admission import admission_key_for

_member = require_role("member")


@_browse_router.get("/user/{user_id}/collection")
async def get_user_collection(user_id: int, auth: dict = Depends(require_auth)):
    """Return Jyzrox collection/subscription state independently of Pixiv follow state."""
    url = f"https://www.pixiv.net/users/{user_id}"
    async with async_session() as session:
        gallery = (
            await session.execute(
                select(Gallery).where(
                    Gallery.source == "pixiv",
                    Gallery.source_id == f"user:{user_id}",
                    Gallery.created_by_user_id == auth["user_id"],
                    Gallery.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        subscription = (
            await session.execute(
                select(Subscription).where(Subscription.user_id == auth["user_id"], Subscription.url == url)
            )
        ).scalar_one_or_none()
        active_job = (
            await session.execute(
                select(DownloadJob)
                .where(
                    DownloadJob.user_id == auth["user_id"],
                    DownloadJob.canonical_url == normalize_download_url(url),
                    DownloadJob.status.in_(("queued", "running", "paused")),
                )
                .order_by(DownloadJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        work_count = 0
        missing_count = 0
        if gallery:
            items = (
                (
                    await session.execute(
                        select(GallerySourceItem.status).where(GallerySourceItem.gallery_id == gallery.id)
                    )
                )
                .scalars()
                .all()
            )
            work_count = len(items)
            missing_count = sum(1 for status in items if status == "source_missing")
    return {
        "gallery_id": gallery.id if gallery else None,
        "gallery_source_id": gallery.source_id if gallery else None,
        "subscribed": subscription is not None and subscription.enabled,
        "subscription_id": subscription.id if subscription else None,
        "job_id": str(active_job.id) if active_job else None,
        "job_status": active_job.status if active_job else None,
        "work_count": work_count,
        "missing_count": missing_count,
    }


async def _enqueue_collection_sync(user_id: int, owner_user_id: int, *, full_reconcile: bool, subscription_id=None):
    url = normalize_download_url(f"https://www.pixiv.net/users/{user_id}")
    async with async_session() as session:
        active = (
            await session.execute(
                select(DownloadJob.id)
                .where(
                    DownloadJob.user_id == owner_user_id,
                    DownloadJob.canonical_url == url,
                    DownloadJob.status.in_(("queued", "running", "paused")),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active:
            return active
        job_id = uuid.uuid4()
        session.add(
            DownloadJob(
                id=job_id,
                url=url,
                canonical_url=url,
                source="pixiv",
                status="queued",
                progress={},
                options={"pixiv_collection": True, "full_reconcile": full_reconcile},
                user_id=owner_user_id,
                subscription_id=subscription_id,
                admission_key=admission_key_for("pixiv", url),
            )
        )
        await session.commit()
    try:
        await core.queue.enqueue(
            "pixiv_collection_job",
            _job_id=str(job_id),
            _timeout=settings.download_job_timeout,
            user_id=user_id,
            owner_user_id=owner_user_id,
            db_job_id=str(job_id),
            full_reconcile=full_reconcile,
            subscription_id=subscription_id,
        )
    except Exception as exc:
        async with async_session() as session:
            await session.execute(
                update(DownloadJob).where(DownloadJob.id == job_id).values(status="failed", error=str(exc))
            )
            await session.commit()
        raise
    return job_id


@_browse_router.post("/user/{user_id}/collection/sync")
async def sync_user_collection(
    user_id: int,
    full_reconcile: bool = Query(default=False),
    auth: dict = Depends(_member),
):
    """Create, incrementally sync, or authoritatively reconcile an author collection."""
    job_id = await _enqueue_collection_sync(user_id, auth["user_id"], full_reconcile=full_reconcile)
    await emit_safe(
        EventType.DOWNLOAD_ENQUEUED,
        actor_user_id=auth["user_id"],
        resource_type="pixiv_author_collection",
        resource_id=user_id,
        job_id=str(job_id),
        full_reconcile=full_reconcile,
    )
    return {"status": "queued", "job_id": str(job_id)}


@_browse_router.post("/user/{user_id}/collection/subscription")
async def subscribe_user_collection(user_id: int, auth: dict = Depends(_member)):
    """Subscribe to Jyzrox author-collection updates; unrelated to Pixiv following."""
    url = f"https://www.pixiv.net/users/{user_id}"
    next_check = datetime.now(UTC)
    async with async_session() as session:
        stmt = (
            pg_insert(Subscription)
            .values(
                user_id=auth["user_id"],
                url=url,
                name=f"Pixiv user {user_id}",
                source="pixiv",
                source_id=str(user_id),
                enabled=True,
                auto_download=True,
                cron_expr="0 */2 * * *",
                next_check_at=next_check,
                download_options={"pixiv_collection": True},
            )
            .on_conflict_do_update(
                constraint="subscriptions_user_id_url_key",
                set_={
                    "enabled": True,
                    "auto_download": True,
                    "source": "pixiv",
                    "source_id": str(user_id),
                    "download_options": {"pixiv_collection": True},
                },
            )
            .returning(Subscription.id)
        )
        sub_id = (await session.execute(stmt)).scalar_one()
        await session.commit()
    await emit_safe(
        EventType.SUBSCRIPTION_CREATED,
        actor_user_id=auth["user_id"],
        resource_type="subscription",
        resource_id=sub_id,
        pixiv_user_id=user_id,
    )
    return {"status": "ok", "subscription_id": sub_id}


@_browse_router.delete("/user/{user_id}/collection/subscription")
async def unsubscribe_user_collection(user_id: int, auth: dict = Depends(_member)):
    """Stop future collection updates without deleting the author gallery."""
    url = f"https://www.pixiv.net/users/{user_id}"
    async with async_session() as session:
        result = await session.execute(
            delete(Subscription)
            .where(Subscription.user_id == auth["user_id"], Subscription.url == url)
            .returning(Subscription.id)
        )
        deleted_id = result.scalar_one_or_none()
        await session.commit()
    if deleted_id:
        await emit_safe(
            EventType.SUBSCRIPTION_DELETED,
            actor_user_id=auth["user_id"],
            resource_type="subscription",
            resource_id=deleted_id,
            pixiv_user_id=user_id,
        )
    return {"status": "ok"}


@_browse_router.get("/user/{user_id}/collection/works")
async def list_user_collection_works(
    user_id: int,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    async with async_session() as session:
        gallery = (
            await session.execute(
                select(Gallery).where(
                    Gallery.source == "pixiv",
                    Gallery.source_id == f"user:{user_id}",
                    Gallery.created_by_user_id == auth["user_id"],
                    Gallery.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not gallery:
            raise HTTPException(status_code=404, detail="Author collection not found")
        query = select(GallerySourceItem).where(GallerySourceItem.gallery_id == gallery.id)
        if status:
            query = query.where(GallerySourceItem.status == status)
        items = (
            (await session.execute(query.order_by(GallerySourceItem.source_position.asc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
    return {
        "works": [
            {
                "source_item_id": item.source_item_id,
                "source_item_url": item.source_item_url,
                "title": item.title,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "page_count": item.page_count,
                "position": item.source_position,
                "status": item.status,
            }
            for item in items
        ]
    }
