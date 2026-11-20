"""Settings: E-Hentai site preference and system alerts."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_auth, require_role
from core.config import settings as app_settings
from core.redis_client import get_redis
from services.cache import dismiss_system_alert, get_system_alerts

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


class DismissAlertRequest(BaseModel):
    message: str


class EhSitePreference(BaseModel):
    use_ex: bool


@router.get("/eh-site")
async def get_eh_site_preference(_: dict = Depends(require_auth)):
    """Get current E-Hentai / ExHentai preference."""
    redis = get_redis()
    pref = await redis.get("setting:eh_use_ex")
    if pref is not None:
        use_ex = pref == b"1"
    else:
        use_ex = app_settings.eh_use_ex
    return {"use_ex": use_ex}


@router.patch("/eh-site")
async def set_eh_site_preference(
    req: EhSitePreference,
    _: dict = Depends(_admin),
):
    """Toggle between E-Hentai and ExHentai."""
    redis = get_redis()
    await redis.set("setting:eh_use_ex", "1" if req.use_ex else "0")
    return {"use_ex": req.use_ex}


# ── Alerts ───────────────────────────────────────────────────────────


@router.get("/alerts")
async def get_alerts(_: dict = Depends(require_auth)):
    """Return queued system alerts (cookie expiry, etc.)."""
    return {"alerts": await get_system_alerts()}


@router.post("/alerts/dismiss")
async def dismiss_alert(req: DismissAlertRequest, _: dict = Depends(require_auth)):
    """Dismiss one queued system alert message across all duplicates."""
    if not req.message:
        raise HTTPException(status_code=400, detail="message is required")
    return {"status": "ok", "dismissed": await dismiss_system_alert(req.message)}
