"""Subscription/followed artist jobs for the worker package."""

import asyncio
import uuid
from datetime import UTC, datetime

from croniter import croniter
from sqlalchemy import select, update

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.utils import normalize_download_url
from db.models import DownloadJob, Subscription
from plugins.models import NewWork
from worker.constants import GROUP_MAX_DURATION, logger
from worker.helpers import _cron_record, _cron_should_run, acquire_lock, release_lock


def _compute_next_check(cron_expr: str | None, base: datetime) -> datetime | None:
    """Compute the next scheduled check time from a cron expression.

    Returns ``None`` when the cron expression is missing or unparseable so the
    caller leaves the existing ``next_check_at`` unchanged rather than crashing
    the enqueue path.
    """
    if not cron_expr:
        return None
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception:
        return None


async def _enqueue_fanbox_posts(ctx: dict, sub, *, force_full_scan: bool) -> dict:
    """Discover Fanbox creator posts and queue each post as its own gallery job."""
    from core.redis_client import publish_job_event
    from plugins.builtin.fanbox.policy import fanbox_policy_from_options
    from plugins.builtin.fanbox.source import FanboxSourcePlugin
    from services.credential import get_credential

    try:
        policy = fanbox_policy_from_options(sub.download_options if isinstance(sub.download_options, dict) else {})
        plugin = FanboxSourcePlugin()
        credential = await get_credential("fanbox")
        # Without a logged-in session, an "all accessible" creator sync means
        # public/free content only. Avoid enqueueing a noisy job for every paid
        # post merely to discover that the account has no entitlement.
        selection_policy = policy
        if not credential and policy.content != "free_only":
            selection_policy = policy.model_copy(update={"content": "free_only"})
        works, latest_id = await plugin.discover_posts(
            sub.url,
            None if force_full_scan else sub.last_item_id,
            selection_policy,
            credential,
        )
    except Exception as exc:
        logger.warning("[subscription] Fanbox discovery failed for sub=%d: %s", sub.id, exc)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription).where(Subscription.id == sub.id).values(last_status="failed", last_error=str(exc))
            )
            await session.commit()
        return {"status": "failed", "error": str(exc)}

    options = {"job_context": "subscription", "fanbox": policy.model_dump(mode="json")}
    enqueued: list[tuple[uuid.UUID, NewWork]] = []
    async with AsyncSessionLocal() as session:
        for work in works:
            canonical_url = normalize_download_url(work.url)
            active = (
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
            if active:
                continue
            job_id = uuid.uuid4()
            session.add(
                DownloadJob(
                    id=job_id,
                    url=canonical_url,
                    canonical_url=canonical_url,
                    source="fanbox",
                    status="queued",
                    progress={},
                    options=options,
                    user_id=sub.user_id,
                    subscription_id=sub.id,
                )
            )
            enqueued.append((job_id, work))
        await session.commit()

    for job_id, work in enqueued:
        await core.queue.enqueue(
            "download_job",
            _job_id=str(job_id),
            _timeout=settings.download_job_timeout,
            url=work.url,
            source="fanbox",
            options=options,
            db_job_id=str(job_id),
            total=None,
        )

    now = datetime.now(UTC)
    values = {
        "last_checked_at": now,
        "last_success_at": now,
        "last_job_id": enqueued[-1][0] if enqueued else None,
        "last_item_id": latest_id or sub.last_item_id,
        "last_status": "queued" if enqueued else "up_to_date",
        "last_error": None,
        "source_id": FanboxSourcePlugin.creator_id_from_url(sub.url),
    }
    if sub.group_id is None:
        next_check = _compute_next_check(sub.cron_expr, now)
        if next_check is not None:
            values["next_check_at"] = next_check
    async with AsyncSessionLocal() as session:
        await session.execute(update(Subscription).where(Subscription.id == sub.id).values(**values))
        await session.commit()

    await publish_job_event(
        {
            "type": "subscription_checked",
            "sub_id": sub.id,
            "status": "ok",
            "job_id": str(enqueued[-1][0]) if enqueued else None,
            "user_id": sub.user_id,
            "discovered": len(works),
            "enqueued": len(enqueued),
        }
    )
    return {"status": "ok", "job_id": str(enqueued[-1][0]) if enqueued else None, "enqueued": len(enqueued)}


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
    lock_key = f"subscription:check_lock:{sub.id}"
    lock_value = await acquire_lock(redis, lock_key, ttl=GROUP_MAX_DURATION)
    if not lock_value:
        logger.info("[subscription] sub=%d check already in progress, skipping", sub.id)
        return {"status": "skipped", "reason": "check_in_progress"}

    try:
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
        from plugins.builtin.gallery_dl._sites import get_site_config

        cfg = get_site_config(source)
        if cfg.credential_requirement == "required":
            from services.credential import get_credential

            cred = await get_credential(cfg.source_id)
            if not cred:
                logger.warning("[subscription] sub=%d source '%s' requires credentials, skipping", sub.id, source)
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(Subscription)
                        .where(Subscription.id == sub.id)
                        .values(
                            last_status="failed",
                            last_error=f"{cfg.name} credentials not configured",
                        )
                    )
                    await session.commit()
                return {"status": "skipped", "reason": "credentials_required"}

        # Fanbox creator URLs are collection endpoints. Discovering first and
        # enqueueing individual post URLs keeps each post as one gallery and
        # lets the per-subscription policy apply before a paid post is fetched.
        if source == "fanbox":
            return await _enqueue_fanbox_posts(ctx, sub, force_full_scan=force_full_scan)

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

        # v3.0: inject subscription context for archive-mode and date-after optimization
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

        # Create download job
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
                    user_id=sub.user_id,
                    subscription_id=sub.id,
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


async def check_single_subscription(ctx: dict, sub_id: int, force_full_scan: bool = False) -> dict:
    """Check a single subscription — enqueue a download job for it.

    force_full_scan: if True, run as Force re-scan (no date-after, no archive).
    """
    from core.redis_client import publish_job_event

    async with AsyncSessionLocal() as session:
        sub = await session.get(Subscription, sub_id)
        if not sub:
            await publish_job_event(
                {
                    "type": "subscription_checked",
                    "sub_id": sub_id,
                    "status": "failed",
                    "job_id": None,
                    "user_id": None,
                }
            )
            return {"status": "failed", "error": "subscription not found"}

    try:
        return await _enqueue_for_subscription(ctx, sub, force_full_scan=force_full_scan, manual=True)
    except Exception as exc:
        logger.error("[subscription] error processing sub %d: %s", sub_id, exc)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.id == sub_id)
                .values(
                    last_checked_at=datetime.now(UTC),
                    last_status="failed",
                    last_error=str(exc)[:500],
                )
            )
            await session.commit()
        await publish_job_event(
            {
                "type": "subscription_checked",
                "sub_id": sub_id,
                "status": "failed",
                "job_id": None,
                "user_id": None,
            }
        )
        return {"status": "failed", "error": str(exc)}


async def check_followed_artists(ctx: dict, user_id: int | None = None) -> dict:
    """Check all enabled subscriptions and enqueue download jobs."""
    if user_id is None:
        if not await _cron_should_run(ctx, "check_subscriptions", "30 */2 * * *"):
            logger.info("[check_followed] Skipping — cron gate not reached")
            return {"status": "skipped"}
        await _cron_record(ctx, "check_subscriptions", "running")

    total_checked = 0
    total_enqueued = 0

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        query = select(Subscription).where(Subscription.enabled.is_(True))
        if user_id:
            query = query.where(Subscription.user_id == user_id)
        else:
            # Only check ungrouped subscriptions whose next_check_at is due
            # (group-assigned subs are handled by subscription_scheduler)
            from sqlalchemy import or_

            query = query.where(
                Subscription.auto_download.is_(True),
                Subscription.group_id.is_(None),
                or_(
                    Subscription.next_check_at.is_(None),
                    Subscription.next_check_at <= now,
                ),
            )
        subs = (await session.execute(query)).scalars().all()

    from worker.subscription_group import _spacing_delay

    for sub in subs:
        try:
            result = await _enqueue_for_subscription(ctx, sub)
            total_checked += 1
            if result.get("status") == "ok":
                total_enqueued += 1
            # Randomized spacing (anti-bot pacing; was a fixed 2s)
            await asyncio.sleep(_spacing_delay())
        except Exception as exc:
            logger.error("[check_followed] error for sub %d (%s): %s", sub.id, sub.name, exc)
            continue

    logger.info("[check_followed] done: checked=%d enqueued=%d", total_checked, total_enqueued)
    if user_id is None:
        await _cron_record(ctx, "check_subscriptions", "ok")
    return {"status": "ok", "checked": total_checked, "enqueued": total_enqueued}
