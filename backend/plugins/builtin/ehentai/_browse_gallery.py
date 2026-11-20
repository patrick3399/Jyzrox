"""E-Hentai browse routes: gallery detail, comments, relationships, previews and images."""

import logging

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.errors import api_error
from plugins.builtin.ehentai._browse_common import _browse_router, _locale, _make_client
from services import cache
from services.cache import push_system_alert

logger = logging.getLogger(__name__)


@_browse_router.get("/gallery/{gid}/{token}/comments")
async def get_gallery_comments(
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Scrape gallery comments (read-only, cached 10min)."""
    cache_key = f"eh:comments:{gid}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return {"gid": gid, "comments": cached}

    client = await _make_client()
    async with client:
        try:
            comments = await client.get_comments(gid, token)
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", "en")
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", "en")
            raise api_error(401, "eh_cookie_invalid", "en")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, comments, 600)  # 10min
    return {"gid": gid, "comments": comments}


# ── Gallery metadata ─────────────────────────────────────────────────


@_browse_router.get("/gallery/{gid}/{token}")
async def get_gallery(
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Get gallery metadata via gdata API (cached 24h)."""
    cached = await cache.get_gallery_cache(gid)
    if cached:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    client = await _make_client()
    async with client:
        try:
            metadata = await client.get_gallery_metadata(gid, token)
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", "en")
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", "en")
            raise api_error(401, "eh_cookie_invalid", "en")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_gallery_cache(gid, metadata)
    return JSONResponse(
        content=metadata,
        headers={"Cache-Control": "private, max-age=3600"},  # 1h browser cache
    )


@_browse_router.get("/gallery/{gid}/{token}/relationships")
async def get_gallery_relationships(
    request: Request,
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Get parent and newer-version links from the EH detail page."""
    cache_key = f"eh:relationships:{gid}:{token}"
    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.get_gallery_relationships(gid, token)
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", _locale(request))
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", _locale(request))
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            raise HTTPException(status_code=502, detail=str(e))

    await cache.set_json(cache_key, result, 3600)
    return result


# ── Preview thumbnails (lightweight — single page scrape) ────────────


@_browse_router.get("/gallery/{gid}/{token}/previews")
async def get_gallery_previews(
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """
    Get preview thumbnail URLs by scraping ONLY page 0 of the gallery detail.
    Returns ~20 lightweight CDN thumbnail URLs.  Very fast (single HTTP request).
    Used for the gallery info page before the user clicks Read.
    """
    cached = await cache.get_preview_cache(gid)
    if cached:
        return JSONResponse(
            content={"gid": gid, "previews": cached},
            headers={"Cache-Control": "private, max-age=3600"},
        )

    client = await _make_client()
    async with client:
        try:
            preview_map = await client.get_previews(gid, token)
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", "en")
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", "en")
            raise api_error(401, "eh_cookie_invalid", "en")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    str_previews = {str(k): v for k, v in preview_map.items()}
    await cache.set_preview_cache(gid, str_previews)
    return JSONResponse(
        content={"gid": gid, "previews": str_previews},
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ── Image token list ─────────────────────────────────────────────────


@_browse_router.get("/gallery/{gid}/{token}/images")
async def get_gallery_images(
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """
    Get image page token map for all pages via gtoken API.
    Result is cached in Redis so image-proxy can use it without the gallery token.
    Returns: {"gid": N, "images": {"1": "pt_token", ...}}
    """
    token_map = await cache.get_imagelist_cache(gid)
    if token_map:
        previews = await cache.get_preview_cache(gid) or {}
        return JSONResponse(
            content={"gid": gid, "images": token_map, "previews": previews},
            headers={"Cache-Control": "private, max-age=86400"},  # 24h — pTokens are stable
        )

    # Need total page count — check gallery cache first
    gallery = await cache.get_gallery_cache(gid)
    if not gallery:
        client = await _make_client()
        async with client:
            gallery = await client.get_gallery_metadata(gid, token)
        await cache.set_gallery_cache(gid, gallery)

    total_pages = gallery["pages"]
    client = await _make_client()
    try:
        async with client:
            raw_map, preview_map = await client.get_image_tokens(gid, token, total_pages)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except httpx.HTTPError as e:
        logger.error("Failed to fetch image tokens for %s: %s", gid, e)
        raise HTTPException(status_code=502, detail=f"EH request failed: {e}")

    str_map = {str(k): v for k, v in raw_map.items()}
    str_previews = {str(k): v for k, v in preview_map.items()}
    await cache.set_imagelist_cache(gid, str_map)
    await cache.set_preview_cache(gid, str_previews)
    return JSONResponse(
        content={"gid": gid, "images": str_map, "previews": str_previews},
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── Paginated image token list ───────────────────────────────────────
