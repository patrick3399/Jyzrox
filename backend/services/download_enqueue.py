"""Shared enqueue logic for download requests (HTTP routers and gallery actions)."""

import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import detect_source, normalize_download_url
from db.models import DownloadJob
from services.download_mode import (
    DOWNLOAD,
)
from services.download_policy import get_credential_policy, normalize_download_options
from services.egress_persona import resolve_admission_key
from worker.helpers import enqueue_download_job

logger = logging.getLogger(__name__)

# Job statuses that count as "active" (not yet terminal)
ACTIVE_JOB_STATUSES = ("queued", "running", "paused")


async def credential_warning(source: str) -> str | None:
    """Return a warning code if the source has no credentials configured.

    Raises HTTPException for sources that strictly require credentials (e.g. Pixiv).
    """
    policy = await get_credential_policy(source)
    if policy.missing_required:
        raise HTTPException(
            status_code=400,
            detail=f"{policy.source_name} credentials not configured. Go to Settings → Credentials to set up.",
        )
    return policy.warning_code


async def check_source_enabled(source: str) -> None:
    """Raise HTTP 400 if the download source is disabled.

    Thin HTTP wrapper around services.source_health.is_source_enabled — that
    function is the boundary-respecting form usable from worker/.
    """
    from services.source_health import is_source_enabled

    if not await is_source_enabled(source):
        raise HTTPException(status_code=400, detail=f"Download source '{source}' is disabled")


async def enqueue_url(
    url: str,
    db: AsyncSession,
    *,
    options: dict | None = None,
    total: int | None = None,
    user_id: int | None = None,
    mode: str = DOWNLOAD,
    subscription_id: int | None = None,
    gallery_id: int | None = None,
) -> dict:
    """Shared enqueue logic: DB record first, then queue.

    Order: create DB record first, then enqueue job.  If the enqueue
    fails the DB record is updated to "failed" so the user can see what
    happened.  This avoids the race where a worker picks up the SAQ job before
    the DB row exists.

    ``mode`` is stamped on the row here and never re-derived at run time (see
    services/download_mode.py); ``subscription_id`` / ``gallery_id`` link the
    job to the subscription or gallery it repairs or updates.

    Returns a dict suitable for use as the HTTP response body.
    """
    canonical_url = normalize_download_url(url)

    # Fast-path duplicate guard. The database's partial unique index is the
    # authoritative guard when concurrent requests race past this query.
    existing_stmt = (
        select(DownloadJob)
        .where(
            DownloadJob.canonical_url == canonical_url,
            DownloadJob.user_id == user_id,
            DownloadJob.status.in_(["queued", "running", "paused"]),
        )
        .limit(1)
    )
    existing_job = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_job:
        return {
            "job_id": str(existing_job.id),
            "status": existing_job.status,
            "source": existing_job.source,
            "warning": None,
        }

    source = detect_source(canonical_url)
    try:
        options = await normalize_download_options(canonical_url, source, options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid download options: {exc}") from exc
    job_id = uuid.uuid4()
    initial_progress = {"total": total} if total is not None else {}

    await check_source_enabled(source)
    warning = await credential_warning(source)

    # 1. Persist DB record first so the worker always finds a matching row.
    try:
        job = DownloadJob(
            id=job_id,
            url=canonical_url,
            canonical_url=canonical_url,
            source=source,
            status="queued",
            progress=initial_progress or {},
            options=options or {},
            mode=mode,
            user_id=user_id,
            subscription_id=subscription_id,
            gallery_id=gallery_id,
            admission_key=await resolve_admission_key(source, canonical_url, subscription_id=subscription_id),
        )
        db.add(job)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing_job = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing_job:
            return {
                "job_id": str(existing_job.id),
                "status": existing_job.status,
                "source": existing_job.source,
                "warning": None,
            }
        logger.exception("[enqueue] active-job uniqueness conflict without an existing row")
        raise HTTPException(status_code=500, detail="Failed to persist download job to database")
    except Exception as exc:
        logger.error("[enqueue] DB insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to persist download job to database")

    # 2. Enqueue job. If this fails, mark the DB record as failed.
    # The shared dispatcher routes on the persisted options (e.g. a Pixiv
    # author URL goes to pixiv_collection_job), same as retry/recovery.
    try:
        await enqueue_download_job(job, str(job_id))
    except Exception as exc:
        logger.error("[enqueue] enqueue failed for job %s: %s", job_id, exc)
        try:
            job.status = "failed"
            job.error = f"Failed to enqueue job: {exc}"
            await db.commit()
        except Exception as db_exc:
            logger.warning("[enqueue] could not mark job %s as failed in DB: %s", job_id, db_exc)
        raise HTTPException(status_code=503, detail="Failed to enqueue download job")

    return {"job_id": str(job_id), "status": "queued", "source": source, "warning": warning}
