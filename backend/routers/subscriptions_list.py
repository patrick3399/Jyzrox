"""Subscription list, latest-jobs and by-gallery lookup endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, or_, select
from sqlalchemy import func as sa_func

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import async_session
from db.models import DownloadJob, Gallery, Subscription
from services.download_mode import find_gallery_subscription, is_account_gallery
from services.subscription_view import checking_flags as _checking_flags
from services.subscription_view import serialize_subscription as _serialize_subscription
from services.url_identity import account_gallery_key

router = APIRouter()

_member = require_role("member")


@router.get("/")
async def list_subscriptions(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    group_id: int | None = Query(default=None),
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
        if group_id is not None:
            query = query.where(Subscription.group_id == group_id)
        # id breaks created_at ties so offset paging neither repeats nor skips rows.
        query = query.order_by(Subscription.created_at.desc(), Subscription.id.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        subs = result.scalars().all()

        gallery_by_sub_id: dict[int, Gallery] = {}
        if subs:
            sub_ids = [s.id for s in subs]
            # Latest job per subscription whose gallery is visible: access
            # filter applies before ranking so hidden galleries never win.
            ranked_jobs = (
                select(
                    DownloadJob.subscription_id.label("sid"),
                    DownloadJob.gallery_id.label("gid"),
                    sa_func.row_number()
                    .over(
                        partition_by=DownloadJob.subscription_id,
                        order_by=(DownloadJob.created_at.desc(), DownloadJob.id.desc()),
                    )
                    .label("rn"),
                )
                .join(Gallery, Gallery.id == DownloadJob.gallery_id)
                .where(
                    DownloadJob.subscription_id.in_(sub_ids),
                    DownloadJob.gallery_id.is_not(None),
                    gallery_access_filter(auth),
                )
                .subquery()
            )
            job_gallery_rows = (
                await session.execute(
                    select(ranked_jobs.c.sid, Gallery)
                    .join(Gallery, Gallery.id == ranked_jobs.c.gid)
                    .where(ranked_jobs.c.rn == 1)
                )
            ).all()
            for sub_id, gallery in job_gallery_rows:
                gallery_by_sub_id[sub_id] = gallery

            # Keep the link stable even if old download jobs are cleaned up.
            urls_missing_job_gallery = [s.url for s in subs if s.id not in gallery_by_sub_id]
            if urls_missing_job_gallery:
                source_url_rows = (
                    (
                        await session.execute(
                            select(Gallery)
                            .where(Gallery.source_url.in_(urls_missing_job_gallery), gallery_access_filter(auth))
                            .order_by(Gallery.source_url.asc(), Gallery.added_at.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
                gallery_by_source_url: dict[str, Gallery] = {}
                for gallery in source_url_rows:
                    if gallery.source_url:
                        gallery_by_source_url.setdefault(gallery.source_url, gallery)
                for sub in subs:
                    if sub.id not in gallery_by_sub_id:
                        gallery = gallery_by_source_url.get(sub.url)
                        if gallery:
                            gallery_by_sub_id[sub.id] = gallery

            # A gallery that came from a plain download, or from a subscription
            # that was deleted and re-added, has no job pointing at this
            # subscription and may carry another spelling of the URL (weibo.cn
            # vs weibo.com). Match on the identity the importer upserts on.
            keys_by_sub = {s.id: account_gallery_key(s.url) for s in subs if s.id not in gallery_by_sub_id}
            wanted_keys = {k for k in keys_by_sub.values() if k is not None}
            if wanted_keys:
                identity_rows = (
                    (
                        await session.execute(
                            select(Gallery)
                            .where(
                                or_(
                                    *(and_(Gallery.source == src, Gallery.source_id == sid) for src, sid in wanted_keys)
                                ),
                                Gallery.deleted_at.is_(None),
                                Gallery.merged_into_gallery_id.is_(None),
                                gallery_access_filter(auth),
                            )
                            .order_by(Gallery.id.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
                gallery_by_key = {}
                for gallery in identity_rows:
                    gallery_by_key.setdefault((gallery.source, gallery.source_id), gallery)
                for sub_id, key in keys_by_sub.items():
                    if key is not None and key in gallery_by_key:
                        gallery_by_sub_id[sub_id] = gallery_by_key[key]

        count_q = select(sa_func.count(Subscription.id)).where(Subscription.user_id == user_id)
        if source:
            count_q = count_q.where(Subscription.source == source)
        if enabled is not None:
            count_q = count_q.where(Subscription.enabled == enabled)
        if group_id is not None:
            count_q = count_q.where(Subscription.group_id == group_id)
        total = (await session.execute(count_q)).scalar() or 0

    checking = await _checking_flags([s.id for s in subs])
    return {
        "subscriptions": [
            _serialize_subscription(s, gallery_by_sub_id.get(s.id), checking=c)
            for s, c in zip(subs, checking, strict=True)
        ],
        "total": total,
    }


@router.get("/latest-jobs")
async def get_latest_jobs(auth: dict = Depends(require_auth)):
    """Latest download job of every subscription the user owns, keyed by subscription id.

    One request replaces a per-subscription ``/{sub_id}/jobs?limit=1`` fan-out,
    which exhausted nginx's per-IP ``api_zone`` burst on the subscriptions page.
    """
    from services.download_presenter import serialize_download_job

    user_id = auth["user_id"]
    async with async_session() as session:
        active = DownloadJob.status.in_(["queued", "running", "paused"])
        prio = case(
            (DownloadJob.status == "running", 0),
            (DownloadJob.status == "paused", 1),
            (DownloadJob.status == "queued", 2),
            else_=3,
        )
        ranked = (
            select(
                DownloadJob.id.label("id"),
                sa_func.row_number()
                .over(
                    partition_by=DownloadJob.subscription_id,
                    order_by=(
                        prio.asc(),
                        case((DownloadJob.status == "queued", DownloadJob.admission_ticket), else_=None)
                        .asc()
                        .nulls_last(),
                        DownloadJob.finished_at.desc().nulls_last(),
                        DownloadJob.created_at.desc(),
                        DownloadJob.id.desc(),
                    ),
                )
                .label("rn"),
            )
            .join(Subscription, Subscription.id == DownloadJob.subscription_id)
            .where(Subscription.user_id == user_id)
            .subquery()
        )
        jobs = (
            (
                await session.execute(
                    select(DownloadJob).join(ranked, ranked.c.id == DownloadJob.id).where(ranked.c.rn == 1)
                )
            )
            .scalars()
            .all()
        )

        gallery_ids = [j.gallery_id for j in jobs if j.gallery_id]
        gallery_map = {}
        if gallery_ids:
            gs = (
                (await session.execute(select(Gallery).where(Gallery.id.in_(gallery_ids), gallery_access_filter(auth))))
                .scalars()
                .all()
            )
            gallery_map = {g.id: g for g in gs}

        # Run = jobs created at or after the oldest still-active job, or the
        # latest batch when nothing is active.
        bounds = (
            select(
                DownloadJob.subscription_id.label("sid"),
                sa_func.coalesce(
                    sa_func.min(DownloadJob.created_at).filter(active), sa_func.max(DownloadJob.created_at)
                ).label("run_start"),
            )
            .join(Subscription, Subscription.id == DownloadJob.subscription_id)
            .where(Subscription.user_id == user_id)
            .group_by(DownloadJob.subscription_id)
            .subquery()
        )
        stopped = DownloadJob.progress["outcome"].as_string() == "stopped"
        bucket = case((and_(DownloadJob.status == "done", stopped), "stopped"), else_=DownloadJob.status)
        rows = (
            await session.execute(
                select(DownloadJob.subscription_id, bucket, sa_func.count())
                .join(
                    bounds,
                    and_(bounds.c.sid == DownloadJob.subscription_id, DownloadJob.created_at >= bounds.c.run_start),
                )
                .group_by(DownloadJob.subscription_id, bucket)
            )
        ).all()
        runs: dict[str, dict[str, int]] = {}
        keys = ("queued", "running", "paused", "done", "stopped", "failed", "partial", "cancelled")
        for sid, status, n in rows:
            run = runs.setdefault(str(sid), {"total": 0, **dict.fromkeys(keys, 0)})
            if status in run:
                run[status] += n
            run["total"] += n

    out_jobs: dict[str, dict] = {}
    for j in jobs:
        gallery = gallery_map.get(j.gallery_id)
        d = serialize_download_job(j, gallery)
        if gallery is not None:
            # Access-filtered above; kept out of the shared presenter on purpose.
            d["gallery_title"] = gallery.title
        out_jobs[str(j.subscription_id)] = d
    return {"jobs": out_jobs, "runs": runs}


@router.get("/by-gallery/{gallery_id}")
async def get_gallery_subscription(gallery_id: int, auth: dict = Depends(_member)):
    """The caller's subscription that covers a gallery, for the gallery page.

    ``subscription`` is the one a gallery update would check (see
    ``find_gallery_subscription``). Without one, ``can_subscribe`` says whether
    the gallery is an account the caller could subscribe to, with
    ``subscribe_url`` the URL to subscribe with.
    """
    async with async_session() as session:
        gallery = (
            await session.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
        ).scalar_one_or_none()
        if gallery is None or gallery.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Gallery not found")
        sub = await find_gallery_subscription(session, gallery.id, auth["user_id"])
        account = sub is None and is_account_gallery(gallery)
    if sub is not None:
        (checking,) = await _checking_flags([sub.id])
        return {
            "subscription": _serialize_subscription(sub, checking=checking),
            "can_subscribe": False,
            "subscribe_url": None,
        }
    return {"subscription": None, "can_subscribe": account, "subscribe_url": gallery.source_url if account else None}
