"""Shared helper functions for the worker package."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy.exc
from croniter import croniter as _croniter_cls

from core.database import AsyncSessionLocal
from core.redis_client import publish_job_event
from db.models import DownloadJob
from worker.constants import _IMAGE_MAGIC, logger


def _validate_image_magic(file_path: Path) -> bool:
    """Validate that a file's content matches expected image magic bytes.

    Returns True if the file appears to be a valid image based on its
    magic bytes matching its file extension. Returns False for mismatches.
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(12)
    except OSError:
        return False

    if len(header) < 3:
        return False

    ext = file_path.suffix.lower()

    for magic, valid_exts in _IMAGE_MAGIC.items():
        if header.startswith(magic):
            return ext in valid_exts

    # Special case: WebP needs RIFF + WEBP check
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return ext == '.webp'

    # Special case: AVIF/HEIC ftyp box (offset 4 = 'ftyp')
    if len(header) >= 8 and header[4:8] == b'ftyp':
        return ext in {'.avif', '.heic'}

    # Unknown magic — reject
    return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _set_job_status(job_id: str | None, status: str, error: str | None = None) -> None:
    if not job_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(job_id))
            if job:
                job.status = status
                if error:
                    job.error = error
                elif status == "running":
                    job.error = None  # clear stale error on restart
                # "paused" is an intermediate state — do not set finished_at
                if status in ("done", "failed", "cancelled", "partial"):
                    job.finished_at = datetime.now(UTC)
                await session.commit()
                try:
                    await publish_job_event({
                        "type": "job_update",
                        "job_id": job_id,
                        "status": status,
                        "progress": job.progress,
                        "user_id": job.user_id,
                    })
                except Exception:
                    pass
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.error("[download] failed to update job status: %s", exc)


async def _set_job_progress(job_id: str | None, progress: dict) -> None:
    """Persist progress JSONB to the DB without changing status or finished_at."""
    if not job_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(job_id))
            if job:
                job.progress = progress
                await session.commit()
                try:
                    await publish_job_event({
                        "type": "job_update",
                        "job_id": job_id,
                        "status": job.status,
                        "progress": progress,
                        "user_id": job.user_id,
                    })
                except Exception:
                    pass
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.warning("[download] failed to update job progress: %s", exc)


def compute_arq_job_id(job_id, retry_count: int) -> str:
    """Compute unique ARQ job ID based on retry count."""
    if retry_count > 0:
        return f"retry:{job_id}:{retry_count}"
    return str(job_id)


async def enqueue_download_job(arq_pool, job, arq_job_id: str) -> None:
    """Enqueue a download job to ARQ with standard parameters."""
    await arq_pool.enqueue_job(
        "download_job",
        job.url,
        job.source or "",
        None,  # options
        str(job.id),
        job.progress.get("total") if job.progress else None,
        _job_id=arq_job_id,
    )


async def _cron_should_run(ctx: dict, task_id: str, default_cron: str, default_enabled: bool = True) -> bool:
    """Check Redis cron config to determine if a scheduled job should run now."""
    r = ctx["redis"]
    enabled = await r.get(f"cron:{task_id}:enabled")
    if enabled == b"0":
        return False
    if enabled is None and not default_enabled:
        return False

    cron_expr = (await r.get(f"cron:{task_id}:cron_expr") or default_cron.encode()).decode()
    last_run_raw = await r.get(f"cron:{task_id}:last_run")
    if last_run_raw:
        last_run = datetime.fromisoformat(last_run_raw.decode())
        it = _croniter_cls(cron_expr, last_run)
        next_run = it.get_next(datetime)
        if datetime.now(UTC) < next_run:
            return False
    return True


async def _cron_record(ctx: dict, task_id: str, status: str, error: str | None = None) -> None:
    """Record the result of a scheduled job execution."""
    r = ctx["redis"]
    pipe = r.pipeline()
    pipe.set(f"cron:{task_id}:last_run", datetime.now(UTC).isoformat())
    pipe.set(f"cron:{task_id}:last_status", status)
    if error:
        pipe.set(f"cron:{task_id}:last_error", error)
    else:
        pipe.delete(f"cron:{task_id}:last_error")
    await pipe.execute()
