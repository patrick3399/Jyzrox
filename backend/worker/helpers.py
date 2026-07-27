"""Shared helper functions for the worker package."""

import hashlib
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy.exc
from croniter import croniter as _croniter_cls

from core.database import AsyncSessionLocal
from core.redis_client import publish_job_event
from db.models import DownloadJob
from services.image_magic import validate_image_magic as _validate_image_magic  # noqa: F401
from worker.constants import logger


def env_int(name: str, default: int) -> int:
    """Read an integer from an environment variable, falling back to `default`."""
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except TypeError, ValueError:
        return default


# _validate_image_magic is aliased above from services.image_magic (single
# source of truth); kept as a private name here for backward compatibility
# with existing worker callers and tests that patch "worker.helpers._validate_image_magic".


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_disk_space(path: str = "/data", min_free_gb: float = 2.0) -> tuple[bool, float]:
    """Return (ok, free_gb). Fail-open on OSError."""
    try:
        usage = shutil.disk_usage(path)
        free_gb = round(usage.free / (1024**3), 2)
        return free_gb >= min_free_gb, free_gb
    except OSError:
        return True, -1.0


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
                    await publish_job_event(
                        {
                            "type": "job_update",
                            "job_id": job_id,
                            "status": status,
                            "progress": job.progress,
                            "user_id": job.user_id,
                        }
                    )
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
                    await publish_job_event(
                        {
                            "type": "job_update",
                            "job_id": job_id,
                            "status": job.status,
                            "progress": progress,
                            "user_id": job.user_id,
                        }
                    )
                except Exception:
                    pass
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.warning("[download] failed to update job progress: %s", exc)


def compute_job_key(job_id, retry_count: int) -> str:
    """Compute unique job key based on retry count."""
    if retry_count > 0:
        return f"retry:{job_id}:{retry_count}"
    return str(job_id)


async def enqueue_download_job(job, job_key: str) -> None:
    """Enqueue a download job with standard parameters."""
    import core.queue
    from core.config import settings

    raw_options = getattr(job, "options", None)
    options = raw_options if isinstance(raw_options, dict) else {}
    if options.get("pixiv_collection") is True:
        from plugins.builtin.pixiv.source import PixivSourcePlugin

        match = PixivSourcePlugin.user_match(job.url)
        if not match or job.user_id is None:
            raise ValueError(f"Invalid persisted Pixiv collection job: {job.id}")
        await core.queue.enqueue(
            "pixiv_collection_job",
            _job_id=job_key,
            _timeout=settings.download_job_timeout,
            user_id=int(match.group(1)),
            owner_user_id=job.user_id,
            db_job_id=str(job.id),
            full_reconcile=bool(options.get("full_reconcile")),
            subscription_id=job.subscription_id,
        )
        return

    await core.queue.enqueue(
        "download_job",
        _job_id=job_key,
        _timeout=settings.download_job_timeout,
        url=job.url,
        source=job.source or "",
        # Policy must survive retry/recovery; queue payloads are ephemeral but
        # DownloadJob.options is persisted with the original request.
        options=options,
        db_job_id=str(job.id),
        total=job.progress.get("total") if job.progress else None,
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

    claimed = await r.set(
        f"cron:{task_id}:claim",
        datetime.now(UTC).isoformat(),
        nx=True,
        ex=60,
    )
    return bool(claimed)


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
    pipe.delete(f"cron:{task_id}:claim")
    await pipe.execute()


# ── Renewable Lock ────────────────────────────────────────────────────

LOCK_RELEASE_LUA = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
LOCK_RENEW_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end"
)


async def acquire_lock(redis, key: str, ttl: int = 300) -> str | None:
    """Acquire a distributed lock with a unique value. Returns lock_value or None."""
    import uuid as _uuid

    lock_value = str(_uuid.uuid4())
    acquired = await redis.set(key, lock_value, nx=True, ex=ttl)
    if acquired:
        return lock_value
    return None


async def release_lock(redis, key: str, lock_value: str) -> bool:
    """Release a lock only if we still own it (compare-and-delete via Lua)."""
    result = await redis.eval(LOCK_RELEASE_LUA, 1, key, lock_value)
    return result == 1


async def renew_lock(redis, key: str, lock_value: str, ttl: int) -> bool:
    """Extend a lock's TTL only if we still own it (compare-and-expire).

    Lets a holder outlive its initial TTL while it is demonstrably still
    working, without ever resetting the expiry on a lock somebody else now
    owns. Returns False once the lock is gone or has changed hands, which the
    caller should treat as having lost mutual exclusion.
    """
    result = await redis.eval(LOCK_RENEW_LUA, 1, key, lock_value, ttl)
    return result == 1
