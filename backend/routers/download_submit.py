"""Download submit endpoints (enqueue by URL, quick download)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from core.utils import normalize_download_url
from services.download_enqueue import enqueue_url as _enqueue
from services.download_mode import (
    find_subscription_for_url,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class DownloadRequest(BaseModel):
    url: str
    source: str = ""  # ignored; kept for backward compat
    options: dict | None = None
    total: int | None = None
    filesize_min: str | None = None  # e.g. "100k", "1M"
    filesize_max: str | None = None  # e.g. "50M", "1G"
    # The URL equals one of the user's subscriptions: enqueueing it anyway
    # resumes history the user may have given up (stop), so it needs a yes.
    confirm_subscribed: bool = False


class QuickDownloadRequest(BaseModel):
    url: str


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
    if not req.confirm_subscribed:
        subscribed = await find_subscription_for_url(db, normalize_download_url(req.url), auth["user_id"])
        if subscribed is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "subscribed",
                    "subscription_id": subscribed.id,
                    "name": subscribed.name or subscribed.url,
                },
            )
    result = await _enqueue(req.url, db, options=merged_options or None, total=req.total, user_id=auth["user_id"])
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.DOWNLOAD_ENQUEUED,
        actor_user_id=auth["user_id"],
        resource_type="download_job",
        resource_id=result.get("job_id"),
    )
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
    return await _enqueue(req.url, db, user_id=auth["user_id"])
