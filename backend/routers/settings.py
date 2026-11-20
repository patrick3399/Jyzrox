"""Credential management and system settings.

Aggregates the per-family sub-routers (credentials, features, EH site and alerts,
API tokens, rate limits, recovery strategy) in their original registration order.
"""

from fastapi import APIRouter

from routers import (
    settings_credentials_eh,
    settings_credentials_misc,
    settings_credentials_pixiv,
    settings_eh_alerts,
    settings_features,
    settings_rate_limits,
    settings_recovery,
    settings_tokens,
)

router = APIRouter(tags=["settings"])

router.include_router(settings_credentials_eh.router)
router.include_router(settings_credentials_pixiv.router)
router.include_router(settings_credentials_misc.router)
router.include_router(settings_features.router)
router.include_router(settings_eh_alerts.router)
router.include_router(settings_tokens.router)
router.include_router(settings_rate_limits.router)
router.include_router(settings_recovery.router)
