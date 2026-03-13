"""Download queue management."""

import logging
import os
import signal
import urllib.parse
import uuid

from arq.connections import ArqRedis

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.config import settings as app_settings
from core.errors import api_error, parse_accept_language
from core.database import get_db
from core.redis_client import get_redis
from core.utils import detect_source, detect_source_info, get_supported_sites
from db.models import DownloadJob
from services.credential import get_credential

logger = logging.getLogger(__name__)
router = APIRouter(tags=["download"])

_member = require_role("member")


class DownloadRequest(BaseModel):
    url: str
    source: str = ""  # ignored; kept for backward compat
    options: dict | None = None  # ignored; kept for backward compat
    total: int | None = None


class QuickDownloadRequest(BaseModel):
    url: str


class JobActionRequest(BaseModel):
    action: str  # "pause" or "resume"


async def _credential_warning(source: str) -> str | None:
    """Return a warning code if the source has no credentials configured.

    Raises HTTPException for sources that strictly require credentials (e.g. Pixiv).
    """
    if source in ("ehentai", "exhentai"):
        cred = await get_credential("ehentai")
        if not cred:
            return "eh_credentials_recommended"
    elif source == "pixiv":
        cred = await get_credential("pixiv")
        if not cred:
            raise HTTPException(
                status_code=400,
                detail="Pixiv credentials not configured. Go to Settings → Credentials to set up.",
            )
    return None


async def _check_source_enabled(source: str) -> None:
    """Raise 400 if the download source is disabled."""
    mapping = {
        "ehentai": ("setting:download_eh_enabled", app_settings.download_eh_enabled),
        "exhentai": ("setting:download_eh_enabled", app_settings.download_eh_enabled),
        "pixiv": ("setting:download_pixiv_enabled", app_settings.download_pixiv_enabled),
    }

    if source in mapping:
        key, default = mapping[source]
        val = await get_redis().get(key)
        enabled = val == b"1" if val is not None else default
        if not enabled:
            raise HTTPException(status_code=400, detail=f"Download source '{source}' is disabled")
    else:
        # gallery-dl fallback
        val = await get_redis().get("setting:download_gallery_dl_enabled")
        enabled = val == b"1" if val is not None else app_settings.download_gallery_dl_enabled
        if not enabled:
            raise HTTPException(status_code=400, detail="gallery-dl downloads are disabled")


async def _enqueue(
    url: str,
    arq,
    db: AsyncSession,
    *,
    options: dict | None = None,
    total: int | None = None,
    user_id: int | None = None,
) -> dict:
    """Shared enqueue logic: DB record first, then ARQ.

    Order: create DB record first, then enqueue ARQ job.  If the ARQ enqueue
    fails the DB record is updated to "failed" so the user can see what
    happened.  This avoids the race where a worker picks up the ARQ job before
    the DB row exists.

    Returns a dict suitable for use as the HTTP response body.
    """
    job_id = uuid.uuid4()
    source = detect_source(url)
    initial_progress = {"total": total} if total is not None else {}

    await _check_source_enabled(source)
    warning = await _credential_warning(source)

    # 1. Persist DB record first so the worker always finds a matching row.
    try:
        job = DownloadJob(id=job_id, url=url, source=source, status="queued", progress=initial_progress or {}, user_id=user_id)
        db.add(job)
        await db.commit()
    except Exception as exc:
        logger.error("[enqueue] DB insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to persist download job to database")

    # 2. Enqueue ARQ job. If this fails, mark the DB record as failed.
    try:
        await arq.enqueue_job(
            "download_job",
            url,
            source,
            options,
            str(job_id),
            total,
            _job_id=str(job_id),
        )
    except Exception as exc:
        logger.error("[enqueue] ARQ enqueue failed for job %s: %s", job_id, exc)
        try:
            job.status = "failed"
            job.error = f"Failed to enqueue job: {exc}"
            await db.commit()
        except Exception as db_exc:
            logger.warning("[enqueue] could not mark job %s as failed in DB: %s", job_id, db_exc)
        raise HTTPException(status_code=503, detail="Failed to enqueue download job")

    return {"job_id": str(job_id), "status": "queued", "source": source, "warning": warning}


@router.post("/")
async def enqueue_download(
    req: DownloadRequest,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    return await _enqueue(req.url, request.app.state.arq, db, options=req.options, total=req.total, user_id=auth["user_id"])


@router.post("/quick")
async def quick_download(
    req: QuickDownloadRequest,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Share-target endpoint: accepts a bare URL and auto-detects the source.

    Designed for the PWA Web Share Target API — mobile users share a URL
    directly to the app and the download is enqueued immediately.
    """
    return await _enqueue(req.url, request.app.state.arq, db, user_id=auth["user_id"])


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    is_admin = auth["role"] == "admin"
    base_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]

    if status:
        conditions = [DownloadJob.status == status] + base_filter
        stmt_filtered = select(DownloadJob).where(*conditions)
        total = (await db.execute(select(func.count()).select_from(stmt_filtered.subquery()))).scalar_one()
        stmt = stmt_filtered.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    else:
        if is_admin:
            # Fast estimated count for unfiltered admin queries
            total = (await db.execute(
                text("SELECT n_live_tup::bigint FROM pg_stat_user_tables WHERE relname = 'download_jobs'")
            )).scalar_one_or_none() or 0
            stmt = select(DownloadJob).order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
        else:
            stmt_filtered = select(DownloadJob).where(*base_filter)
            total = (await db.execute(select(func.count()).select_from(stmt_filtered.subquery()))).scalar_one()
            stmt = stmt_filtered.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()

    return {"total": total, "jobs": [_j(j) for j in jobs]}


@router.delete("/jobs")
async def clear_finished_jobs(
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Delete all completed, failed, and cancelled jobs."""
    conditions = [DownloadJob.status.in_(["done", "failed", "cancelled", "partial"])]
    if auth["role"] != "admin":
        conditions.append(DownloadJob.user_id == auth["user_id"])
    stmt = delete(DownloadJob).where(*conditions)
    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/stats")
async def get_stats(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return counts of running and finished jobs for nav badge polling."""
    is_admin = auth["role"] == "admin"
    user_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]
    running_count = (
        await db.execute(
            select(func.count()).where(DownloadJob.status.in_(["queued", "running", "paused"]), *user_filter)
        )
    ).scalar_one()
    finished_count = (
        await db.execute(
            select(func.count()).where(DownloadJob.status.in_(["done", "failed", "cancelled", "partial"]), *user_filter)
        )
    ).scalar_one()
    return {"running": running_count, "finished": finished_count}


@router.get("/check-url")
async def check_url(
    url: str = Query(...),
    _: dict = Depends(require_auth),
):
    """Check whether a URL is from a known supported site."""
    entry = detect_source_info(url)
    if entry is not None:
        return {
            "supported": True,
            "source_id": entry["source_id"],
            "name": entry["name"],
            "category": entry["category"],
        }

    # Not in registry — treat as supported if it looks like a valid URL (gallery-dl fallback)
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme and parsed.netloc:
            return {
                "supported": True,
                "source_id": "gallery_dl",
                "name": "gallery-dl",
                "category": "other",
            }
    except Exception:
        pass

    return {"supported": False}


@router.get("/supported-sites")
async def supported_sites(
    _: dict = Depends(require_auth),
):
    """Return all supported download sites grouped by category."""
    return {"categories": get_supported_sites()}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)
    return _j(job)


@router.patch("/jobs/{job_id}")
async def pause_resume_job(
    job_id: uuid.UUID,
    body: JobActionRequest,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Pause or resume a running download job via Redis soft-pause key.

    The worker's pause_check callback reads download:pause:{job_id} from Redis
    and suspends iteration cooperatively. This works for all job types (gallery-dl
    subprocess and native plugin downloads) without relying on cross-container
    PID signalling, which is not possible since the api and worker containers have
    separate PID namespaces.
    """
    if body.action not in ("pause", "resume"):
        raise HTTPException(status_code=400, detail="action must be 'pause' or 'resume'")

    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    redis = get_redis()
    pause_key = f"download:pause:{job_id}"
    terminal_statuses = {"done", "failed", "cancelled", "partial"}
    if body.action == "pause":
        if job.status in terminal_statuses:
            raise HTTPException(status_code=409, detail=f"Job already {job.status}")
        if job.status == "paused":
            # Already in the desired state — no-op, return current status
            return {"status": job.status}
        # job.status == "running" — valid transition
        await redis.set(pause_key, b"1", ex=86400)  # 24h TTL as safety net
        job.status = "paused"
    else:  # resume
        if job.status in terminal_statuses:
            raise HTTPException(status_code=409, detail=f"Job already {job.status}")
        if job.status == "running":
            # Already in the desired state — no-op, return current status
            return {"status": job.status}
        # job.status == "paused" — valid transition
        await redis.delete(pause_key)
        job.status = "running"

    await db.commit()
    return {"status": job.status}


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    if job.status not in ("queued", "running", "paused"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel: status={job.status}")

    # Kill the subprocess if it is running or paused
    redis = get_redis()
    pid_bytes = await redis.get(f"download:pid:{job_id}")
    if pid_bytes:
        try:
            pid = int(pid_bytes)
            # Verify PID belongs to gallery-dl before sending signal
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmdline = fh.read()
                if b"gallery-dl" not in cmdline:
                    logger.warning("[cancel] pid %d is not gallery-dl; skipping signal", pid)
                else:
                    os.kill(pid, signal.SIGTERM)
            except FileNotFoundError:
                pass  # Process already gone
        except (ValueError, PermissionError) as exc:
            logger.warning("[cancel] failed to kill pid %s: %s", pid_bytes, exc)
        await redis.delete(f"download:pid:{job_id}")

    # Also set Redis cancel flag for native downloads (no PID)
    await redis.setex(f"download:cancel:{job_id}", 3600, "1")

    job.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Manually retry a failed or partial download job."""
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id != auth["user_id"] and auth["role"] != "admin":
        locale = parse_accept_language(request.headers.get("accept-language"))
        raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)

    if job.status not in ("failed", "partial"):
        raise HTTPException(status_code=400, detail=f"Cannot retry: status={job.status}")
    if job.retry_count >= job.max_retries:
        raise HTTPException(status_code=400, detail="Max retries reached")

    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)

    job.retry_count += 1
    job.status = "queued"
    job.finished_at = None
    job.error = None

    # Read base_delay from Redis for backoff calculation
    redis = get_redis()
    base_delay_raw = await redis.get("setting:retry_base_delay_minutes")
    base_delay = int(base_delay_raw) if base_delay_raw else 5
    backoff_minutes = min(base_delay * (2 ** job.retry_count), 1440)
    job.next_retry_at = now + timedelta(minutes=backoff_minutes)

    await db.commit()

    arq_job_id = f"retry:{job.id}:{job.retry_count}"
    try:
        arq: ArqRedis = request.app.state.arq
        await arq.enqueue_job(
            "download_job",
            job.url,
            job.source or "",
            None,
            str(job.id),
            job.progress.get("total") if job.progress else None,
            _job_id=arq_job_id,
        )
    except Exception as exc:
        logger.error("[retry] manual retry enqueue failed for %s: %s", job_id, exc)
        job.retry_count -= 1
        job.status = "failed"
        job.error = f"Retry enqueue failed: {exc}"
        await db.commit()
        raise HTTPException(status_code=503, detail="Failed to enqueue retry job")

    return {"status": "queued", "retry_count": job.retry_count, "max_retries": job.max_retries}


def _j(j: DownloadJob) -> dict:
    return {
        "id": str(j.id),
        "url": j.url,
        "source": j.source,
        "status": j.status,
        "progress": j.progress,
        "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "retry_count": j.retry_count,
        "max_retries": j.max_retries,
        "next_retry_at": j.next_retry_at.isoformat() if j.next_retry_at else None,
        "gallery_id": j.gallery_id,
    }
