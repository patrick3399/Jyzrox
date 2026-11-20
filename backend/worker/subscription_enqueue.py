"""Per-subscription check: lock, gates, and download job enqueue."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.utils import normalize_download_url
from db.models import DownloadJob, Subscription
from services.download_admission import admission_key_for
from services.download_mode import subscription_mode
from services.subscription_pause import check_lock_key
from worker.constants import GROUP_MAX_DURATION, logger
from worker.helpers import acquire_lock, release_lock
from worker.subscription_discovery import _compute_next_check, _current_paused_at, _enqueue_discovered_works


async def _enqueue_for_subscription(ctx: dict, sub, force_full_scan: bool = False, manual: bool = False) -> dict:
    """Create a download job for a subscription and enqueue it.

    force_full_scan=True suppresses both date-after and gallery-dl's archive.
    Used by manual ``Force re-scan`` when an interrupted or inconsistent run
    left archive entries without matching image/library rows. Existing local
    images are retained by the importer and social reordering keeps them in the
    gallery sequence even if the remote post disappeared.

    manual=True (user-triggered single check) bypasses the consecutive-failure
    backoff gate — the user explicitly asked for this check.
    """
    from core.redis_client import get_redis, publish_job_event

    pool = ctx.get("redis")
    if not pool:
        return {"status": "failed", "error": "no redis pool"}

    # Race-condition guard: use Redis SETNX so only one concurrent check per sub
    # proceeds. The TTL must cover the longest a single check can run, which is
    # bounded by the group timeout (edge case #32) — a shorter TTL could expire
    # mid-check and let another run enqueue a duplicate for the same sub. The
    # lock is released in `finally`, so this longer TTL only delays recovery
    # after a hard worker crash.
    redis = get_redis()
    lock_key = check_lock_key(sub.id)
    lock_value = await acquire_lock(redis, lock_key, ttl=GROUP_MAX_DURATION)
    if not lock_value:
        logger.info("[subscription] sub=%d check already in progress, skipping", sub.id)
        return {"status": "skipped", "reason": "check_in_progress"}

    try:
        # Re-read under the lock: the row passed in may predate a pause (ADR 0030).
        if await _current_paused_at(sub.id) is not None:
            logger.info("[subscription] sub=%d paused, skipping check", sub.id)
            return {"status": "skipped", "reason": "paused"}
        await publish_job_event({"type": "subscription_checking", "sub_id": sub.id, "user_id": sub.user_id})

        # DL-007: back off automatic checks for chronically failing subs
        # (expired cookies, dead accounts). Manual checks bypass the gate.
        if not manual:
            from services.subscription_health import should_backoff

            skip, failures = await should_backoff(sub.id, getattr(sub, "last_checked_at", None))
            if skip:
                logger.info(
                    "[subscription] sub=%d in failure backoff (%d consecutive failures), skipping",
                    sub.id,
                    failures,
                )
                return {"status": "skipped", "reason": "failure_backoff", "failures": failures}

        # Source-enabled check
        source = sub.source or "gallery_dl"
        from services.source_health import is_source_enabled

        if not await is_source_enabled(source):
            logger.warning("[subscription] sub=%d source '%s' disabled, skipping", sub.id, source)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription)
                    .where(Subscription.id == sub.id)
                    .values(
                        last_status="failed",
                        last_error=f"Download source '{source}' is disabled",
                    )
                )
                await session.commit()
            return {"status": "skipped", "reason": "source_disabled"}

        # Credential check — skip if required credentials are missing
        from services.download_policy import get_credential_policy

        policy = await get_credential_policy(source)
        if policy.missing_required:
            logger.warning("[subscription] sub=%d source '%s' requires credentials, skipping", sub.id, source)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription)
                    .where(Subscription.id == sub.id)
                    .values(
                        last_status="failed",
                        last_error=f"{policy.source_name} credentials not configured",
                    )
                )
                await session.commit()
            return {"status": "skipped", "reason": "credentials_required"}

        # Subscribable sources support per-work incremental discovery: fetching
        # first and enqueueing individual work URLs keeps each work as one
        # gallery and lets the per-subscription policy apply before a paid or
        # gated work is fetched. Sources without the capability fall back to
        # enqueueing the subscription URL as one archive-refresh job below.
        from plugins.registry import plugin_registry

        subscriber = plugin_registry.get_subscriber(source)
        if subscriber is not None:
            return await _enqueue_discovered_works(ctx, sub, subscriber, force_full_scan=force_full_scan)

        canonical_url = normalize_download_url(sub.url)

        # Duplicate guard: skip if this user already has a queued/running/paused job for this URL
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(
                    select(DownloadJob.id)
                    .where(
                        DownloadJob.canonical_url == canonical_url,
                        DownloadJob.user_id == sub.user_id,
                        DownloadJob.status.in_(["queued", "running", "paused"]),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                logger.info(
                    "[subscription] sub=%d URL already has active job %s for user %d, skipping",
                    sub.id,
                    existing,
                    sub.user_id,
                )
                return {"status": "skipped", "reason": "active_job_exists"}

        # v3.0: inject subscription context for skip and date-after optimization
        options: dict = {
            "job_context": "subscription",
        }
        # Credentials are global account state. This per-subscription policy is
        # intentionally copied into the queued job so different creators can
        # use different free/paid selection rules.
        if isinstance(getattr(sub, "download_options", None), dict):
            options.update(sub.download_options)
        if force_full_scan:
            # Force re-scan: bypass date-after and archive so gallery-dl emits
            # every currently visible item; importer-side dedupe preserves local rows.
            options["force_full_scan"] = True
        elif getattr(sub, "last_success_at", None):
            # Incremental: must be JSON-serializable for SAQ; download.py parses
            # back to datetime. last_checked_at is only an attempt timestamp and
            # must not advance gallery-dl incremental cutoffs after failed jobs.
            options["last_completed_at"] = sub.last_success_at.isoformat()

        # Create download job. The mode is stamped here and never re-derived at
        # run time, so retries and recovery replay it. force_full_scan stays in
        # the options too so a not-yet-upgraded worker (rolling deploy) still
        # runs a repair as before.
        mode = subscription_mode(
            has_boundary=bool(getattr(sub, "last_success_at", None)), force_full_scan=force_full_scan
        )
        job_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            session.add(
                DownloadJob(
                    id=job_id,
                    url=canonical_url,
                    canonical_url=canonical_url,
                    source=sub.source or "gallery_dl",
                    status="queued",
                    progress={},
                    options=options,
                    mode=mode,
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                    admission_key=admission_key_for(sub.source or "gallery_dl", canonical_url),
                )
            )
            await session.commit()

        is_pixiv_collection = source == "pixiv" and bool(options.get("pixiv_collection"))
        if is_pixiv_collection:
            from plugins.builtin.pixiv.source import PixivSourcePlugin

            match = PixivSourcePlugin.user_match(sub.url)
            if not match:
                raise ValueError(f"Invalid Pixiv author subscription URL: {sub.url}")
            await core.queue.enqueue(
                "pixiv_collection_job",
                _job_id=str(job_id),
                _timeout=settings.download_job_timeout,
                user_id=int(match.group(1)),
                owner_user_id=sub.user_id,
                db_job_id=str(job_id),
                full_reconcile=False,
                subscription_id=sub.id,
            )
        else:
            await core.queue.enqueue(
                "download_job",
                _job_id=str(job_id),
                _timeout=settings.download_job_timeout,
                url=sub.url,
                source=sub.source or "gallery_dl",
                options=options,
                db_job_id=str(job_id),
                total=None,
            )

        # Update subscription state after a successful enqueue.
        now = datetime.now(UTC)
        values = {
            "last_checked_at": now,
            "last_job_id": job_id,
            "last_status": "queued",
            "last_error": None,
        }
        # Ungrouped subscriptions are gated by next_check_at in check_followed_artists;
        # advance it from the per-sub cron so the schedule is honored instead of being
        # re-checked on every 2h scheduler pass (edge-case audit #9). Group-assigned
        # subs are scheduled by subscription_scheduler and ignore next_check_at.
        if sub.group_id is None:
            next_check = _compute_next_check(sub.cron_expr, now)
            if next_check is not None:
                values["next_check_at"] = next_check
        async with AsyncSessionLocal() as session:
            await session.execute(update(Subscription).where(Subscription.id == sub.id).values(**values))
            await session.commit()

        # WS event
        await publish_job_event(
            {
                "type": "subscription_checked",
                "sub_id": sub.id,
                "status": "ok",
                "job_id": str(job_id),
                "user_id": sub.user_id,
            }
        )

        return {"status": "ok", "job_id": str(job_id)}
    finally:
        await release_lock(redis, lock_key, lock_value)
