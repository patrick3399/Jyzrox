"""E-Hentai browse routes: image proxy and favorites."""

import logging

import httpx
from fastapi import Depends, HTTPException, Query, Request, Response

from core.auth import require_auth
from core.errors import api_error
from core.rate_limit import _is_private, check_rate_limit, get_client_ip
from core.redis_client import eh_semaphore
from plugins.builtin.ehentai._browse_common import _browse_router, _locale, _make_client
from plugins.builtin.ehentai._browse_paginated import _resolve_ptoken_on_demand
from services import cache
from services.cache import push_system_alert
from services.credential import get_credential

logger = logging.getLogger(__name__)


@_browse_router.get("/image-proxy/{gid}/{page}")
async def image_proxy(
    request: Request,
    gid: int,
    page: int,
    auth: dict = Depends(require_auth),
):
    """
    Proxy a gallery image through the server.

    Flow:
      1. Check Redis cache (TTL 24h) — return if hit
      2. Look up image page token from imagelist cache; on miss, fetch the
         containing detail page on demand (see _resolve_ptoken_on_demand)
      3. Acquire global EH semaphore (max EH_MAX_CONCURRENCY)
      4. Fetch image page HTML → extract image URL
      5. Fetch image bytes → cache → return
    """
    # 1. Cache hit
    cached_bytes = await cache.get_proxied_image(gid, page)
    if cached_bytes:
        from services.eh_client import detect_media_type

        return Response(
            content=cached_bytes,
            media_type=detect_media_type(cached_bytes),
            headers={"Cache-Control": "private, max-age=86400"},  # 24h
        )

    # Rate-limit the outbound EH fetch, not the request. The budget exists to keep
    # us from hammering EH, so only a cache miss — the one branch that actually
    # leaves our network — spends it. Charging cache hits burned the whole budget
    # on ordinary fast page-flipping through already-fetched pages.
    if not _is_private(get_client_ip(request)):
        await check_rate_limit(f"img_proxy:eh:{auth['user_id']}", max_requests=600, window=60)

    # 2. Resolve image page token — imagelist cache first, then on-demand fetch
    token_map = await cache.get_imagelist_cache(gid) or {}
    image_page_token = token_map.get(str(page))
    if not image_page_token:
        image_page_token = await _resolve_ptoken_on_demand(gid, page)
    if not image_page_token:
        raise HTTPException(
            status_code=404,
            detail=f"Page {page} of gallery {gid} not in cache. Call /api/eh/gallery/{{gid}}/{{token}}/images first.",
        )

    # 3–5. Fetch under semaphore
    client = await _make_client()
    async with client:
        try:
            async with eh_semaphore.acquire():
                image_url = await client.get_image_url(image_page_token, gid, page)
                image_bytes, media_type = await client.fetch_image_bytes(image_url)
        except TimeoutError:
            raise HTTPException(status_code=503, detail="EH semaphore timeout")
        except httpx.TimeoutException as e:
            logger.warning("EH image request timed out for gallery %s page %s: %s", gid, page, e)
            raise HTTPException(status_code=504, detail="EH image request timed out") from e
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", "en")
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", "en")
            raise api_error(401, "eh_cookie_invalid", "en")

    await cache.set_proxied_image(gid, page, image_bytes)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── Favorites ─────────────────────────────────────────────────────────


@_browse_router.get("/favorites/{gid}/{token}")
async def get_favorite_state(
    request: Request,
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Return the authenticated user's EH cloud favorite state."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise api_error(400, "eh_not_configured", _locale(request))

    client = await _make_client()
    async with client:
        try:
            return await client.get_favorite_state(gid, token)
        except PermissionError:
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            logger.error("Failed to read favorite state for %s/%s: %s", gid, token, e)
            raise HTTPException(status_code=502, detail=str(e))


@_browse_router.get("/favorites")
async def get_favorites(
    request: Request,
    favcat: str = Query(default="all"),
    q: str = Query(default=""),
    next: str = Query(default="", alias="next"),
    prev: str = Query(default="", alias="prev"),
    _: dict = Depends(require_auth),
):
    """Browse EH cloud favorites with cursor-based pagination."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise api_error(400, "eh_not_configured", _locale(request))

    cache_key = f"eh:favorites:{favcat}:{next}:{prev}:{q}"
    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.get_favorites(
                favcat=favcat,
                search=q,
                next_cursor=next,
                prev_cursor=prev,
            )
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", _locale(request))
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", _locale(request))
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, result, 120)  # 2min cache — favorites change often
    return result


# ── Favorite management ──────────────────────────────────────────────


@_browse_router.post("/favorites/{gid}/{token}")
async def add_favorite(
    request: Request,
    gid: int,
    token: str,
    favcat: int = Query(default=0, ge=0, le=9),
    note: str = Query(default=""),
    _: dict = Depends(require_auth),
):
    """Add/move gallery to a cloud favorites category."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise api_error(400, "eh_not_configured", _locale(request))

    client = await _make_client()
    async with client:
        try:
            await client.add_favorite(gid, token, favcat=favcat, note=note)
        except PermissionError:
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            logger.error("Failed to add favorite %s/%s: %s", gid, token, e)
            raise HTTPException(status_code=502, detail=str(e))

    return {"status": "ok"}


@_browse_router.delete("/favorites/{gid}/{token}")
async def remove_favorite(
    request: Request,
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Remove gallery from cloud favorites."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise api_error(400, "eh_not_configured", _locale(request))

    client = await _make_client()
    async with client:
        try:
            await client.remove_favorite(gid, token)
        except PermissionError:
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            logger.error("Failed to remove favorite %s/%s: %s", gid, token, e)
            raise HTTPException(status_code=502, detail=str(e))

    return {"status": "ok"}


# ── Thumbnail proxy ───────────────────────────────────────────────────
