"""External API download enqueue endpoint."""

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

import core.queue
from core.config import settings
from core.database import async_session
from core.utils import detect_source, normalize_download_url
from db.models import DownloadJob
from services.external_auth import verify_api_token

logger = logging.getLogger(__name__)

router = APIRouter()


class ExternalDownloadRequest(BaseModel):
    url: str


@router.post("/download")
async def enqueue_download(
    request: Request,
    body: ExternalDownloadRequest | None = None,
    url: str | None = Query(default=None),
    token_data: dict = Depends(verify_api_token),
):
    """Enqueue a download job via external API.

    Accepts the target URL either as a JSON body field ``url`` or as a query
    parameter ``url``.  JSON body takes priority; if both are absent a 422 is
    returned.

    Order: SAQ enqueue first, then DB commit. If SAQ fails we never create the
    DB record. If DB insert fails after a successful SAQ enqueue we log a
    warning — the SAQ job will time out naturally without a matching DB record.
    """
    resolved_url = (body.url if body else None) or url
    if not resolved_url:
        raise HTTPException(status_code=422, detail="Missing 'url' in body or query parameter")

    # Viewers cannot trigger downloads
    from core.auth import ROLE_HIERARCHY

    if ROLE_HIERARCHY.get(token_data.get("role", ""), 0) < ROLE_HIERARCHY["member"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions: member role required")

    resolved_url = normalize_download_url(resolved_url)
    job_id = _uuid.uuid4()
    source = detect_source(resolved_url)
    from services.egress_persona import resolve_admission_key

    # Persist first so workers can never observe a queue entry without its DB
    # identity. The partial unique index closes concurrent duplicate races.
    admission_key = await resolve_admission_key(source, resolved_url, subscription_id=None)
    try:
        async with async_session() as session:
            session.add(
                DownloadJob(
                    id=job_id,
                    url=resolved_url,
                    canonical_url=resolved_url,
                    source=source,
                    status="queued",
                    user_id=token_data["user_id"],
                    admission_key=admission_key,
                )
            )
            await session.commit()
    except IntegrityError:
        async with async_session() as session:
            existing = (
                await session.execute(
                    select(DownloadJob).where(
                        DownloadJob.user_id == token_data["user_id"],
                        DownloadJob.canonical_url == resolved_url,
                        DownloadJob.status.in_(("queued", "running", "paused")),
                    )
                )
            ).scalar_one_or_none()
        if existing:
            return {"job_id": str(existing.id), "status": existing.status}
        raise HTTPException(status_code=500, detail="Failed to persist download job to database")
    except Exception as exc:
        logger.error("[external/enqueue] DB insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to persist download job to database")

    try:
        await core.queue.enqueue(
            "download_job",
            _job_id=str(job_id),
            _timeout=settings.download_job_timeout,
            url=resolved_url,
            source=source,
            options=None,
            db_job_id=str(job_id),
            total=None,
        )
    except Exception as exc:
        logger.error("[external/enqueue] enqueue failed: %s", exc)
        async with async_session() as session:
            await session.execute(
                update(DownloadJob)
                .where(DownloadJob.id == job_id)
                .values(status="failed", error=f"Queue unavailable: {exc}")
            )
            await session.commit()
        raise HTTPException(status_code=503, detail="Failed to enqueue download job")

    return {"job_id": str(job_id), "status": "queued"}
