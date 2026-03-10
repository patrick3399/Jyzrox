"""Subscription/followed artist jobs for the worker package."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter as _croniter_cls
from sqlalchemy import update
from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import DownloadJob, Gallery, Subscription
from services.credential import get_credential
from worker.constants import _BOORU_SOURCES, logger
from worker.helpers import _cron_record, _cron_should_run


async def check_followed_artists(ctx: dict, user_id: int | None = None) -> dict:
    """Check followed Pixiv artists for new works and optionally enqueue downloads."""
    import asyncio as _asyncio

    from db.models import Subscription
    from services.pixiv_client import PixivClient

    # When called as a cron job (no explicit user_id), apply cron gating.
    # When called directly with a user_id (manual trigger), always run.
    if user_id is None:
        if not await _cron_should_run(ctx, "check_subscriptions", "30 */2 * * *"):
            logger.info("[check_followed] Skipping — cron gate not reached")
            return {"status": "skipped"}
        await _cron_record(ctx, "check_subscriptions", "running")

    refresh_token = await get_credential("pixiv")
    if not refresh_token:
        logger.info("[check_followed] no Pixiv credentials configured — skipping")
        return {"status": "skipped", "reason": "No Pixiv credentials"}

    async with AsyncSessionLocal() as session:
        query = select(Subscription).where(Subscription.source == "pixiv")
        if user_id:
            query = query.where(Subscription.user_id == user_id)
        result = await session.execute(query)
        artists = result.scalars().all()

    if not artists:
        return {"status": "ok", "checked": 0}

    checked = 0
    new_works = 0
    pool = ctx.get("redis")

    async with PixivClient(refresh_token) as client:
        for artist in artists:
            try:
                data = await client.user_illusts(int(artist.source_id))
                illusts = data.get("illusts", [])

                if illusts:
                    newest_id = str(illusts[0].get("id", ""))

                    if newest_id and newest_id != artist.last_item_id:
                        # Determine how many works are truly new
                        new_count = 0
                        if artist.last_item_id:
                            for ill in illusts:
                                if str(ill.get("id", "")) == artist.last_item_id:
                                    break
                                new_count += 1
                        else:
                            new_count = len(illusts)

                        new_works += new_count

                        # Derive updated artist name from response
                        updated_name = (
                            (illusts[0].get("user") or {}).get("name")
                            or artist.name
                        )

                        async with AsyncSessionLocal() as session:
                            await session.execute(
                                update(Subscription).where(
                                    Subscription.id == artist.id
                                ).values(
                                    last_checked_at=datetime.now(UTC),
                                    last_item_id=newest_id,
                                    name=updated_name,
                                )
                            )
                            await session.commit()

                        # Auto-download new works if enabled
                        if artist.auto_download and new_count > 0 and pool:
                            for ill in illusts[:new_count]:
                                illust_url = f"https://www.pixiv.net/artworks/{ill['id']}"
                                try:
                                    job_id = uuid.uuid4()
                                    async with AsyncSessionLocal() as db_session:
                                        db_session.add(DownloadJob(
                                            id=job_id,
                                            url=illust_url,
                                            source="pixiv",
                                            status="queued",
                                            progress={},
                                        ))
                                        await db_session.commit()
                                    await pool.enqueue_job(
                                        "download_job",
                                        illust_url,
                                        "pixiv",
                                        None,
                                        str(job_id),
                                        None,
                                        _job_id=str(job_id),
                                    )
                                except Exception as enq_exc:
                                    logger.warning(
                                        "[check_followed] failed to enqueue auto-download for illust %s: %s",
                                        ill.get("id"),
                                        enq_exc,
                                    )
                    else:
                        # No new works — just update the check timestamp
                        async with AsyncSessionLocal() as session:
                            await session.execute(
                                update(Subscription).where(
                                    Subscription.id == artist.id
                                ).values(last_checked_at=datetime.now(UTC))
                            )
                            await session.commit()

                checked += 1
                await _asyncio.sleep(2)  # Pixiv rate limit

            except Exception as exc:
                logger.error(
                    "[check_followed] error checking artist %s (%s): %s",
                    artist.source_id,
                    artist.name,
                    exc,
                )
                continue

    logger.info("[check_followed] done: checked=%d new_works=%d", checked, new_works)
    if user_id is None:
        await _cron_record(ctx, "check_subscriptions", "ok")
    return {"status": "ok", "checked": checked, "new_works": new_works}


async def check_single_subscription(ctx: dict, sub_id: int) -> dict:
    """Check a single subscription for new works."""
    from db.models import Subscription
    from services.pixiv_client import PixivClient

    async with AsyncSessionLocal() as session:
        sub = await session.get(Subscription, sub_id)
        if not sub:
            return {"status": "failed", "error": "subscription not found"}

    if sub.source == "pixiv" and sub.source_id:
        refresh_token = await get_credential("pixiv")
        if not refresh_token:
            return {"status": "failed", "error": "No Pixiv credentials"}

        new_count = 0
        try:
            async with PixivClient(refresh_token) as client:
                data = await client.user_illusts(int(sub.source_id))
                illusts = data.get("illusts", [])

                if illusts:
                    newest_id = str(illusts[0].get("id", ""))

                    if newest_id and newest_id != sub.last_item_id:
                        if sub.last_item_id:
                            for ill in illusts:
                                if str(ill.get("id", "")) == sub.last_item_id:
                                    break
                                new_count += 1
                        else:
                            new_count = len(illusts)

                        async with AsyncSessionLocal() as session:
                            await session.execute(
                                update(Subscription).where(
                                    Subscription.id == sub.id
                                ).values(
                                    last_checked_at=datetime.now(UTC),
                                    last_item_id=newest_id,
                                    name=(illusts[0].get("user") or {}).get("name") or sub.name,
                                    last_status="ok",
                                    last_error=None,
                                )
                            )
                            await session.commit()

                        if sub.auto_download and new_count > 0:
                            pool = ctx.get("redis")
                            if pool:
                                for ill in illusts[:new_count]:
                                    illust_url = f"https://www.pixiv.net/artworks/{ill['id']}"
                                    try:
                                        job_id = uuid.uuid4()
                                        async with AsyncSessionLocal() as db_session:
                                            db_session.add(DownloadJob(
                                                id=job_id, url=illust_url,
                                                source="pixiv", status="queued", progress={},
                                            ))
                                            await db_session.commit()
                                        await pool.enqueue_job(
                                            "download_job", illust_url, "pixiv",
                                            None, str(job_id), None,
                                            _job_id=str(job_id),
                                        )
                                    except Exception as enq_exc:
                                        logger.warning("[check_sub] failed to enqueue: %s", enq_exc)
                    else:
                        async with AsyncSessionLocal() as session:
                            await session.execute(
                                update(Subscription).where(
                                    Subscription.id == sub.id
                                ).values(
                                    last_checked_at=datetime.now(UTC),
                                    last_status="ok",
                                    last_error=None,
                                )
                            )
                            await session.commit()

            return {"status": "ok", "new_works": new_count}

        except Exception as exc:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription).where(Subscription.id == sub.id).values(
                        last_checked_at=datetime.now(UTC),
                        last_status="failed",
                        last_error=str(exc)[:500],
                    )
                )
                await session.commit()
            return {"status": "failed", "error": str(exc)}

    else:
        # Generic: enqueue download_job for the URL
        pool = ctx.get("redis")
        if pool and sub.auto_download:
            try:
                job_id = uuid.uuid4()
                async with AsyncSessionLocal() as db_session:
                    db_session.add(DownloadJob(
                        id=job_id, url=sub.url,
                        source=sub.source or "gallery_dl", status="queued", progress={},
                    ))
                    await db_session.commit()
                await pool.enqueue_job(
                    "download_job", sub.url, sub.source or "gallery_dl",
                    None, str(job_id), None,
                    _job_id=str(job_id),
                )
            except Exception as exc:
                logger.warning("[check_sub] failed to enqueue generic download: %s", exc)

        async with AsyncSessionLocal() as session:
            next_check = _croniter_cls(sub.cron_expr or "0 */2 * * *", datetime.now(UTC)).get_next(datetime)
            await session.execute(
                update(Subscription).where(Subscription.id == sub.id).values(
                    last_checked_at=datetime.now(UTC),
                    last_status="ok",
                    last_error=None,
                    next_check_at=next_check,
                )
            )
            await session.commit()

        return {"status": "ok"}


async def backfill_artist_ids(ctx: dict) -> dict:
    """One-time backfill: populate artist_id for existing galleries."""
    logger.info("[backfill] starting artist_id backfill")
    updated = 0
    async with AsyncSessionLocal() as session:
        # Fetch all galleries without artist_id
        rows = (await session.execute(
            select(Gallery).where(Gallery.artist_id.is_(None))
        )).scalars().all()

        for g in rows:
            aid = None
            if g.source == "ehentai":
                for tag in (g.tags_array or []):
                    if tag.startswith("artist:"):
                        aid = f"ehentai:{tag[7:]}"
                        break
            elif g.source == "pixiv":
                if g.uploader:
                    aid = f"pixiv:{g.uploader}"
            elif g.source in ("twitter", "gallery_dl") and g.category == "twitter":
                if g.uploader:
                    aid = f"twitter:{g.uploader}"
            else:
                if g.uploader:
                    aid = f"{g.source}:{g.uploader}"

            if aid:
                g.artist_id = aid
                updated += 1

        await session.commit()

    logger.info("[backfill] updated %d galleries", updated)
    return {"status": "done", "updated": updated}
