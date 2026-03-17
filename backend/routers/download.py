"""Download queue management."""

import logging
import os
import re
import signal
import urllib.parse
import uuid

from arq.connections import ArqRedis

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from worker.helpers import compute_arq_job_id, enqueue_download_job
from core.config import settings as app_settings
from core.errors import api_error, parse_accept_language
from core.database import get_db
from core.redis_client import get_redis
from core.utils import detect_source, detect_source_info, get_supported_sites
from db.models import DownloadJob, Gallery
from services.credential import get_credential

logger = logging.getLogger(__name__)
router = APIRouter(tags=["download"])

_member = require_role("member")


class DownloadRequest(BaseModel):
    url: str
    source: str = ""  # ignored; kept for backward compat
    options: dict | None = None
    total: int | None = None
    filesize_min: str | None = None  # e.g. "100k", "1M"
    filesize_max: str | None = None  # e.g. "50M", "1G"


class QuickDownloadRequest(BaseModel):
    url: str


class JobActionRequest(BaseModel):
    action: str  # "pause" or "resume"


class PreviewResponse(BaseModel):
    source: str
    preview_available: bool
    title: str | None = None
    pages: int | None = None
    tags: list[str] | None = None
    uploader: str | None = None
    rating: float | None = None
    thumb_url: str | None = None
    category: str | None = None


async def _credential_warning(source: str) -> str | None:
    """Return a warning code if the source has no credentials configured.

    Raises HTTPException for sources that strictly require credentials (e.g. Pixiv).
    """
    from plugins.builtin.gallery_dl._sites import get_site_config
    cfg = get_site_config(source)
    if cfg.credential_requirement == "none":
        return None
    cred = await get_credential(cfg.source_id)
    if cfg.credential_requirement == "required" and not cred:
        raise HTTPException(
            status_code=400,
            detail=f"{cfg.name} credentials not configured. Go to Settings → Credentials to set up.",
        )
    if cfg.credential_requirement == "recommended" and not cred:
        return cfg.credential_warning_code
    return None


async def _check_source_enabled(source: str) -> None:
    """Raise 400 if the download source is disabled."""
    from plugins.builtin.gallery_dl._sites import get_site_config
    cfg = get_site_config(source)
    if cfg.feature_toggle_key and cfg.feature_toggle_attr:
        default = getattr(app_settings, cfg.feature_toggle_attr, True)
        val = await get_redis().get(cfg.feature_toggle_key)
        enabled = val == b"1" if val is not None else default
    else:
        val = await get_redis().get("setting:download_gallery_dl_enabled")
        enabled = val == b"1" if val is not None else app_settings.download_gallery_dl_enabled
    if not enabled:
        raise HTTPException(status_code=400, detail=f"Download source '{source}' is disabled")


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
    # Duplicate guard: return existing job if same URL + same user is already active
    existing_stmt = select(DownloadJob).where(
        DownloadJob.url == url,
        DownloadJob.user_id == user_id,
        DownloadJob.status.in_(["queued", "running"]),
    ).limit(1)
    existing_job = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_job:
        return {"job_id": str(existing_job.id), "status": existing_job.status, "source": existing_job.source, "warning": None}

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
    merged_options = dict(req.options or {})
    if req.filesize_min:
        merged_options["filesize_min"] = req.filesize_min
    if req.filesize_max:
        merged_options["filesize_max"] = req.filesize_max
    result = await _enqueue(req.url, request.app.state.arq, db, options=merged_options or None, total=req.total, user_id=auth["user_id"])
    try:
        from core.events import EventType, emit
        await emit(EventType.DOWNLOAD_ENQUEUED, actor_user_id=auth["user_id"], resource_type="download_job", resource_id=result.get("job_id"))
    except Exception:
        pass
    return result


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
    exclude_subscription: bool = Query(default=False),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    is_admin = auth["role"] == "admin"
    base_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]
    if exclude_subscription:
        base_filter.append(DownloadJob.subscription_id.is_(None))

    if status:
        conditions = [DownloadJob.status == status] + base_filter
        stmt_filtered = select(DownloadJob).where(*conditions)
        total = (await db.execute(select(func.count()).select_from(stmt_filtered.subquery()))).scalar_one()
        stmt = stmt_filtered.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    else:
        if is_admin and not base_filter:
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

    # Batch-load galleries for jobs that have gallery_id
    gallery_ids = [j.gallery_id for j in jobs if j.gallery_id]
    gallery_map: dict[int, Gallery] = {}
    if gallery_ids:
        gs = (await db.execute(select(Gallery).where(Gallery.id.in_(gallery_ids)))).scalars().all()
        gallery_map = {g.id: g for g in gs}

    return {"total": total, "jobs": [_j(j, gallery_map.get(j.gallery_id)) for j in jobs]}


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
    exclude_subscription: bool = Query(default=False),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return counts of running and finished jobs for nav badge polling."""
    is_admin = auth["role"] == "admin"
    user_filter = [] if is_admin else [DownloadJob.user_id == auth["user_id"]]
    if exclude_subscription:
        user_filter.append(DownloadJob.subscription_id.is_(None))
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


_EH_URL_RE = re.compile(r"https?://e[-x]hentai\.org/g/(\d+)/([a-f0-9]{10})/?")
_PIXIV_URL_RE = re.compile(r"https?://(?:www\.)?pixiv\.net/(?:\w+/)?artworks/(\d+)")


@router.get("/preview", response_model=PreviewResponse)
async def preview_url(
    url: str = Query(...),
    _: dict = Depends(require_auth),
):
    """Preview metadata for a URL before downloading.

    Returns structured preview data for supported sources (EH, Pixiv).
    For gallery-dl sites without a dedicated client, returns preview_available=False
    with basic site info so the frontend can still confirm the URL is recognised.
    """
    source = detect_source(url)

    if source == "unknown":
        raise HTTPException(status_code=400, detail="Unsupported URL")

    # E-Hentai / ExHentai preview
    eh_match = _EH_URL_RE.match(url)
    if eh_match:
        gid = int(eh_match.group(1))
        token = eh_match.group(2)
        try:
            import json as _json
            from core.redis_client import get_redis as _get_redis
            from core.config import settings as _cfg
            from services.credential import get_credential as _get_cred
            from services.eh_client import EhClient as _EhClient

            cred_json = await _get_cred("ehentai")
            cookies = _json.loads(cred_json) if cred_json else {}
            pref = await _get_redis().get("setting:eh_use_ex")
            if pref is not None:
                use_ex = pref == b"1"
            else:
                use_ex = _cfg.eh_use_ex or bool(cookies.get("igneous"))

            async with _EhClient(cookies=cookies, use_ex=use_ex) as client:
                meta = await client.get_gallery_metadata(gid, token)

            return PreviewResponse(
                source="ehentai",
                preview_available=True,
                title=meta.get("title") or meta.get("title_jpn") or None,
                pages=meta.get("pages"),
                tags=(meta.get("tags") or [])[:30] or None,
                uploader=meta.get("uploader") or None,
                rating=float(meta["rating"]) if meta.get("rating") else None,
                thumb_url=meta.get("thumb") or None,
                category=meta.get("category") or None,
            )
        except Exception as exc:
            logger.warning("[preview] EH metadata fetch failed for %s: %s", url, exc)

    # Pixiv preview
    pixiv_match = _PIXIV_URL_RE.search(url)
    if pixiv_match:
        illust_id = int(pixiv_match.group(1))
        try:
            from services.credential import get_credential as _get_cred
            from services.pixiv_client import PixivClient as _PixivClient

            refresh_token = await _get_cred("pixiv")
            if refresh_token:
                async with _PixivClient(refresh_token=refresh_token) as client:
                    illust = await client.illust_detail(illust_id)

                tags = [t.get("name", "") for t in (illust.get("tags") or []) if t.get("name")]
                user = illust.get("user") or {}
                image_urls = illust.get("image_urls") or {}
                return PreviewResponse(
                    source="pixiv",
                    preview_available=True,
                    title=illust.get("title") or None,
                    pages=illust.get("page_count"),
                    tags=tags[:30] or None,
                    uploader=user.get("name") or None,
                    thumb_url=image_urls.get("square_medium") or None,
                )
        except Exception as exc:
            logger.warning("[preview] Pixiv metadata fetch failed for %s: %s", url, exc)

    # Fallback for gallery-dl sites (and EH/Pixiv when metadata fetch fails)
    site_info = detect_source_info(url)
    return PreviewResponse(
        source=source,
        preview_available=False,
        title=site_info.get("name") if site_info else None,
        category=site_info.get("category") if site_info else None,
    )


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
    gallery = None
    if job.gallery_id:
        gallery = await db.get(Gallery, job.gallery_id)
    return _j(job, gallery)


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
        await db.commit()
        return {"status": job.status}
    else:  # resume
        if job.status in terminal_statuses:
            raise HTTPException(status_code=409, detail=f"Job already {job.status}")
        if job.status == "running":
            # Already in the desired state — no-op, return current status
            return {"status": job.status}
        # job.status == "paused" or "queued" — valid transition
        await redis.delete(pause_key)

        # Check if the ARQ coroutine is still alive.
        # ARQ writes arq:result:{job_id} when a job finishes (success or failure).
        arq_job_id = compute_arq_job_id(job.id, job.retry_count)
        arq_result = await redis.get(f"arq:result:{arq_job_id}")

        if arq_result is not None:
            # Coroutine is dead — re-enqueue as a new ARQ job.
            # Prepare re-enqueue before committing DB changes to avoid orphaning
            # the job in "queued" state if the enqueue fails after commit.
            new_retry_count = job.retry_count + 1
            new_arq_id = compute_arq_job_id(job.id, new_retry_count)
            arq_pool: ArqRedis = request.app.state.arq

            try:
                await enqueue_download_job(arq_pool, job, new_arq_id)
            except Exception:
                raise HTTPException(status_code=503, detail="Failed to re-enqueue job")

            job.retry_count = new_retry_count
            job.status = "queued"
            job.error = None
            job.finished_at = None
            await db.commit()
            return {"status": "queued", "restarted": True}
        else:
            # Coroutine still alive — just flip the flag
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
    try:
        from core.events import EventType, emit
        await emit(EventType.DOWNLOAD_CANCELLED, actor_user_id=auth["user_id"], resource_type="download_job", resource_id=str(job_id))
    except Exception:
        pass
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

    arq_job_id = compute_arq_job_id(job.id, job.retry_count)
    try:
        arq: ArqRedis = request.app.state.arq
        await enqueue_download_job(arq, job, arq_job_id)
    except Exception as exc:
        logger.error("[retry] manual retry enqueue failed for %s: %s", job_id, exc)
        job.retry_count -= 1
        job.status = "failed"
        job.error = f"Retry enqueue failed: {exc}"
        await db.commit()
        raise HTTPException(status_code=503, detail="Failed to enqueue retry job")

    return {"status": "queued", "retry_count": job.retry_count, "max_retries": job.max_retries}


def _j(j: DownloadJob, gallery: Gallery | None = None) -> dict:
    d = {
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
        "subscription_id": j.subscription_id,
    }
    if gallery:
        d["gallery_source"] = gallery.source
        d["gallery_source_id"] = gallery.source_id
    return d
