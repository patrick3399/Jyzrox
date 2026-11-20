"""External API endpoints for third-party integrations."""

from fastapi import APIRouter, Depends, HTTPException

from core.config import settings
from core.redis_client import get_redis

from . import external_download, external_images, external_status


async def _require_external_api_enabled():
    """Raise 404 if External API feature is disabled."""
    val = await get_redis().get("setting:external_api_enabled")
    if val is not None:
        enabled = val == b"1"
    else:
        enabled = settings.external_api_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="External API is disabled")


router = APIRouter(tags=["external"], dependencies=[Depends(_require_external_api_enabled)])

router.include_router(external_status.router)
router.include_router(external_images.router)
router.include_router(external_download.router)
