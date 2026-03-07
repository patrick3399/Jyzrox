"""Download queue management."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import get_db
from db.models import DownloadJob

logger = logging.getLogger(__name__)
router = APIRouter(tags=["download"])


class DownloadRequest(BaseModel):
    url: str
    source: str = ""
    options: dict = {}


@router.post("/")
async def enqueue_download(
    req: DownloadRequest,
    request: Request,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a DB download record and enqueue an ARQ job."""
    job_id = uuid.uuid4()

    # DB record
    job = DownloadJob(id=job_id, url=req.url, source=req.source, status="queued")
    db.add(job)
    await db.commit()

    # Enqueue via shared ARQ pool (created at app startup)
    arq = request.app.state.arq
    await arq.enqueue_job(
        "download_job",
        req.url,
        req.source,
        req.options,
        str(job_id),       # db_job_id parameter
        _job_id=str(job_id),
    )

    return {"job_id": str(job_id), "status": "queued"}


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DownloadJob)
    if status:
        stmt = stmt.where(DownloadJob.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(desc(DownloadJob.created_at)).offset(page * limit).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()

    return {"total": total, "jobs": [_j(j) for j in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _j(job)


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: uuid.UUID,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel: status={job.status}")
    job.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}


def _j(j: DownloadJob) -> dict:
    return {
        "id":          str(j.id),
        "url":         j.url,
        "source":      j.source,
        "status":      j.status,
        "progress":    j.progress,
        "error":       j.error,
        "created_at":  j.created_at.isoformat() if j.created_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }
