"""Source-enablement check.

Single source of truth for "is this download source allowed to run right now?"
Used by both routers (which translate to HTTP 400) and workers (which mark the
subscription as failed). Lives in services/ so worker/* does not depend on
routers/* (STAB-003).
"""

from __future__ import annotations

from core.config import settings as app_settings
from core.redis_client import get_redis


async def is_source_enabled(source: str) -> bool:
    """Return True if the download source is currently enabled.

    Resolution order:
      1. Site-specific feature toggle (Redis key + settings attr from site config)
      2. Global gallery-dl toggle (Redis key + settings.download_gallery_dl_enabled)
    """
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    if cfg.feature_toggle_key and cfg.feature_toggle_attr:
        default = getattr(app_settings, cfg.feature_toggle_attr, True)
        val = await get_redis().get(cfg.feature_toggle_key)
        return val == b"1" if val is not None else default
    val = await get_redis().get("setting:download_gallery_dl_enabled")
    return val == b"1" if val is not None else app_settings.download_gallery_dl_enabled
