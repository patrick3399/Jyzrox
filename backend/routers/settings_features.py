"""Settings: feature toggles."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete

from core.auth import require_auth, require_role
from core.config import settings as app_settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import BlobRelationship
from services.settings_store import (
    get_float_setting as _get_float_setting,
)
from services.settings_store import (
    get_int_setting as _get_int_setting,
)
from services.settings_store import (
    get_toggle as _get_toggle,
)
from services.settings_store import (
    set_toggle as _set_toggle,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


class FeatureTogglePatch(BaseModel):
    enabled: bool | None = None
    value: int | float | None = None


@router.get("/features")
async def get_feature_toggles(_: dict = Depends(require_auth)):
    """Get all feature toggle states."""
    return {
        "csrf_enabled": await _get_toggle("setting:csrf_enabled", app_settings.csrf_enabled),
        "rate_limit_enabled": await _get_toggle("setting:rate_limit_enabled", app_settings.rate_limit_enabled),
        "opds_enabled": await _get_toggle("setting:opds_enabled", app_settings.opds_enabled),
        "external_api_enabled": await _get_toggle("setting:external_api_enabled", app_settings.external_api_enabled),
        "novel_enabled": await _get_toggle("setting:novel_enabled", app_settings.novel_enabled),
        "tag_translation_enabled": await _get_toggle("setting:tag_translation_enabled", True),
        "download_eh_enabled": await _get_toggle("setting:download_eh_enabled", app_settings.download_eh_enabled),
        "download_pixiv_enabled": await _get_toggle(
            "setting:download_pixiv_enabled", app_settings.download_pixiv_enabled
        ),
        "download_gallery_dl_enabled": await _get_toggle(
            "setting:download_gallery_dl_enabled", app_settings.download_gallery_dl_enabled
        ),
        "dedup_phash_enabled": await _get_toggle("setting:dedup_phash_enabled", False),
        "dedup_heuristic_enabled": await _get_toggle("setting:dedup_heuristic_enabled", False),
        "dedup_phash_threshold": await _get_int_setting("setting:dedup_phash_threshold", 10),
        "dedup_opencv_enabled": await _get_toggle("setting:dedup_opencv_enabled", False),
        "dedup_opencv_threshold": await _get_float_setting("setting:dedup_opencv_threshold", 0.85),
        "retry_enabled": await _get_toggle("setting:retry_enabled", True),
        "retry_max_retries": await _get_int_setting("setting:retry_max_retries", 3),
        "retry_base_delay_minutes": await _get_int_setting("setting:retry_base_delay_minutes", 5),
        "subscription_enqueue_delay_ms": await _get_int_setting("setting:subscription_enqueue_delay_ms", 500),
        "subscription_batch_max": await _get_int_setting("setting:subscription_batch_max", 0),
        "gallery_update_check_days": await _get_int_setting("setting:gallery_update_check_days", 14),
        "trash_enabled": await _get_toggle("setting:trash_enabled", True),
        "trash_retention_days": await _get_int_setting("setting:trash_retention_days", 30),
    }


@router.patch("/features/{feature}")
async def patch_feature_toggle(
    feature: str,
    req: FeatureTogglePatch,
    _: dict = Depends(_admin),
):
    """Toggle a feature on/off."""
    ALLOWED = {
        "csrf_enabled": "setting:csrf_enabled",
        "rate_limit_enabled": None,  # special case: modifies app_settings directly
        "opds_enabled": "setting:opds_enabled",
        "external_api_enabled": "setting:external_api_enabled",
        "novel_enabled": "setting:novel_enabled",
        "tag_translation_enabled": "setting:tag_translation_enabled",
        "download_eh_enabled": "setting:download_eh_enabled",
        "download_pixiv_enabled": "setting:download_pixiv_enabled",
        "download_gallery_dl_enabled": "setting:download_gallery_dl_enabled",
        "dedup_phash_enabled": "setting:dedup_phash_enabled",
        "dedup_heuristic_enabled": "setting:dedup_heuristic_enabled",
        "dedup_phash_threshold": "setting:dedup_phash_threshold",
        "dedup_opencv_enabled": "setting:dedup_opencv_enabled",
        "dedup_opencv_threshold": "setting:dedup_opencv_threshold",
        "retry_enabled": "setting:retry_enabled",
        "retry_max_retries": "setting:retry_max_retries",
        "retry_base_delay_minutes": "setting:retry_base_delay_minutes",
        "subscription_enqueue_delay_ms": "setting:subscription_enqueue_delay_ms",
        "subscription_batch_max": "setting:subscription_batch_max",
        "gallery_update_check_days": "setting:gallery_update_check_days",
        "trash_enabled": "setting:trash_enabled",
        "trash_retention_days": "setting:trash_retention_days",
    }
    if feature not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    redis_key = ALLOWED.get(feature)

    if feature == "dedup_phash_threshold":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for dedup_phash_threshold")
        threshold = int(req.value)
        if float(req.value) != threshold or not (0 <= threshold <= 20):
            raise HTTPException(status_code=400, detail="dedup_phash_threshold must be an integer between 0 and 20")
        from worker.dedup_helpers import AUTO_CANDIDATE_RELATIONSHIPS

        async with async_session() as session:
            result = await session.execute(
                delete(BlobRelationship).where(
                    BlobRelationship.decision.is_(None),
                    BlobRelationship.relationship.in_(AUTO_CANDIDATE_RELATIONSHIPS),
                    BlobRelationship.hamming_dist > threshold,
                )
            )
            await session.commit()
        removed = int(result.rowcount or 0)
        await get_redis().set("setting:dedup_phash_threshold", str(threshold))
        return {"feature": feature, "value": threshold, "removed_candidates": removed}

    if feature == "dedup_opencv_threshold":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for dedup_opencv_threshold")
        await get_redis().set("setting:dedup_opencv_threshold", str(req.value))
        return {"feature": feature, "value": req.value}

    if feature == "retry_max_retries":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for retry_max_retries")
        val = int(req.value)
        if not (1 <= val <= 10):
            raise HTTPException(status_code=400, detail="retry_max_retries must be between 1 and 10")
        await get_redis().set("setting:retry_max_retries", str(val))
        return {"feature": feature, "value": val}

    if feature == "retry_base_delay_minutes":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for retry_base_delay_minutes")
        val = int(req.value)
        if not (1 <= val <= 60):
            raise HTTPException(status_code=400, detail="retry_base_delay_minutes must be between 1 and 60")
        await get_redis().set("setting:retry_base_delay_minutes", str(val))
        return {"feature": feature, "value": val}

    if feature == "subscription_enqueue_delay_ms":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for subscription_enqueue_delay_ms")
        val = int(req.value)
        if val < 100:
            raise HTTPException(status_code=400, detail="subscription_enqueue_delay_ms must be >= 100")
        await get_redis().set("setting:subscription_enqueue_delay_ms", str(val))
        return {"feature": feature, "value": val}

    if feature == "subscription_batch_max":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for subscription_batch_max")
        val = int(req.value)
        if val < 0:
            raise HTTPException(status_code=400, detail="subscription_batch_max must be >= 0")
        await get_redis().set("setting:subscription_batch_max", str(val))
        return {"feature": feature, "value": val}

    if feature == "gallery_update_check_days":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for gallery_update_check_days")
        val = int(req.value)
        if val < -1:
            raise HTTPException(status_code=400, detail="gallery_update_check_days must be >= -1")
        await get_redis().set("setting:gallery_update_check_days", str(val))
        return {"feature": feature, "value": val}

    if feature == "trash_retention_days":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for trash_retention_days")
        val = int(req.value)
        if not (1 <= val <= 365):
            raise HTTPException(status_code=400, detail="trash_retention_days must be between 1 and 365")
        await get_redis().set("setting:trash_retention_days", str(val))
        return {"feature": feature, "value": val}

    if req.enabled is None:
        raise HTTPException(status_code=400, detail="enabled required for boolean features")

    if feature == "rate_limit_enabled":
        app_settings.rate_limit_enabled = req.enabled
        await get_redis().set("setting:rate_limit_enabled", "1" if req.enabled else "0")
        return {"feature": feature, "enabled": req.enabled}

    await _set_toggle(redis_key, req.enabled)
    return {"feature": feature, "enabled": req.enabled}
