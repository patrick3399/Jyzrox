"""Admin API for gallery-dl venv management (upgrade/rollback)."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core.auth import require_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["gallery-dl admin"])

_admin = require_role("admin")


class UpgradeRequest(BaseModel):
    version: str | None = None


@router.get("/version")
async def get_gallery_dl_version(_: dict = Depends(_admin)):
    """Return current and latest available gallery-dl versions."""
    from worker.gallery_dl_venv import get_current_version, get_latest_pypi_version

    current, latest = await asyncio.gather(get_current_version(), get_latest_pypi_version())
    return {"current": current, "latest": latest}


@router.post("/upgrade")
async def upgrade_gallery_dl(
    request: Request,
    body: UpgradeRequest | None = None,
    _: dict = Depends(_admin),
):
    """Enqueue gallery-dl upgrade job."""
    arq = request.app.state.arq
    version = body.version if body else None
    job = await arq.enqueue_job("gdl_upgrade_job", version)
    return {"job_id": job.job_id}


@router.post("/rollback")
async def rollback_gallery_dl(
    request: Request,
    _: dict = Depends(_admin),
):
    """Enqueue gallery-dl rollback job."""
    arq = request.app.state.arq
    job = await arq.enqueue_job("gdl_rollback_job")
    return {"job_id": job.job_id}
