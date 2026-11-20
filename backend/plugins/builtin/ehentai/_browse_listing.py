"""E-Hentai browse routes: popular and toplists."""

from fastapi import Depends, HTTPException, Query, Request

from core.auth import require_auth
from core.errors import api_error
from plugins.builtin.ehentai._browse_common import (
    _browse_router,
    _filter_blocked,
    _get_blocked_tags,
    _locale,
    _make_client,
)
from services import cache
from services.cache import push_system_alert


@_browse_router.get("/popular")
async def get_popular(
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Get EH popular galleries (scrape /popular, cached 5min)."""
    cache_key = "eh:popular"
    cached = await cache.get_json(cache_key)
    if cached:
        user_id = auth["user_id"]
        blocked = await _get_blocked_tags(user_id)
        if blocked and cached.get("galleries"):
            cached["galleries"] = _filter_blocked(cached["galleries"], blocked)
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.get_popular()
        except PermissionError as e:
            detail = str(e)
            if "509" in detail:
                await push_system_alert(detail)
                raise api_error(403, "eh_bandwidth_exceeded", _locale(request))
            if "Sad Panda" in detail:
                await push_system_alert(detail)
                raise api_error(403, "eh_access_denied", _locale(request))
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, result, 300)  # 5min

    user_id = auth["user_id"]
    blocked = await _get_blocked_tags(user_id)
    if blocked and result.get("galleries"):
        result["galleries"] = _filter_blocked(result["galleries"], blocked)

    return result


# ── Top Lists ─────────────────────────────────────────────────────────

_VALID_TL = {11, 12, 13, 15}


@_browse_router.get("/toplists")
async def get_toplist(
    request: Request,
    tl: int = Query(default=11, description="11=All-Time, 12=Past Year, 13=Past Month, 15=Yesterday"),
    page: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
):
    """Get EH top list galleries (scrape /toplist.php, cached 10min)."""
    if tl not in _VALID_TL:
        raise HTTPException(status_code=400, detail=f"Invalid tl value. Must be one of {sorted(_VALID_TL)}")

    cache_key = f"eh:toplist:{tl}:{page}"
    cached = await cache.get_json(cache_key)
    if cached:
        user_id = auth["user_id"]
        blocked = await _get_blocked_tags(user_id)
        if blocked and cached.get("galleries"):
            cached["galleries"] = _filter_blocked(cached["galleries"], blocked)
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.get_toplist(tl=tl, page=page)
        except PermissionError as e:
            detail = str(e)
            if "509" in detail:
                await push_system_alert(detail)
                raise api_error(403, "eh_bandwidth_exceeded", _locale(request))
            if "Sad Panda" in detail:
                await push_system_alert(detail)
                raise api_error(403, "eh_access_denied", _locale(request))
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, result, 600)  # 10min

    user_id = auth["user_id"]
    blocked = await _get_blocked_tags(user_id)
    if blocked and result.get("galleries"):
        result["galleries"] = _filter_blocked(result["galleries"], blocked)

    return result


# ── Gallery Comments ──────────────────────────────────────────────────
