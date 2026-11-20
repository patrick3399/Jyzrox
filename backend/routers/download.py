"""Download queue management."""

from fastapi import APIRouter

from services.download_enqueue import check_source_enabled as _check_source_enabled
from services.download_enqueue import credential_warning as _credential_warning
from services.download_enqueue import enqueue_url as _enqueue

from . import download_actions, download_job_ops, download_jobs, download_submit
from .download_job_ops import retry_job as retry_job

router = APIRouter(tags=["download"])

router.include_router(download_submit.router)
router.include_router(download_jobs.router)
router.include_router(download_job_ops.router)
router.include_router(download_actions.router)

__all__ = ["_check_source_enabled", "_credential_warning", "_enqueue", "retry_job", "router"]
