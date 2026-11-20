"""Pixiv browse routes: following list, feed and image proxy."""

import hashlib
import logging
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException, Query, Request, Response

from core.auth import require_auth
from core.rate_limit import _is_private, check_rate_limit, get_client_ip
from plugins.builtin.pixiv._browse_common import _browse_router, _detect_media_type, _make_client, _pximg_headers
from services import cache
from services.browser_http import browser_client

logger = logging.getLogger(__name__)

_ALLOWED_PXIMG_HOSTS = {"i.pximg.net", "i-f.pximg.net", "s.pximg.net"}


# ── My following list ────────────────────────────────────────────────


@_browse_router.get("/following")
async def get_my_following(
    restrict: str = Query(default="public"),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Get the currently authenticated user's Pixiv following list (cached 5min)."""
    cache_key = f"my_following:{restrict}:{offset}"
    cached = await cache.get_pixiv_search_cache(cache_key)
    if cached is not None:
        return cached

    client = await _make_client()
    async with client:
        try:
            from core.redis_client import get_redis

            r = get_redis()
            rt_tail = client.refresh_token[-10:] if client.refresh_token else "none"
            uid_key = f"pixiv:uid:{rt_tail}"
            uid = await r.get(uid_key)

            if uid:
                user_id = int(uid.decode() if isinstance(uid, bytes) else uid)
            else:
                await client._refresh_token()
                user_id = client._api.user_id
                if user_id:
                    await r.setex(uid_key, 86400 * 30, str(user_id))
                else:
                    raise PermissionError("Could not determine Pixiv user_id")

            result = await client.user_following(user_id, restrict=restrict, offset=offset)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_search_cache(cache_key, result)
    return result


# ── Following feed ───────────────────────────────────────────────────


@_browse_router.get("/following/feed")
async def get_following_feed(
    restrict: str = Query(default="public"),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Get new works from followed artists (cached 5min)."""
    cache_key = f"following_feed:{restrict}:{offset}"
    cached = await cache.get_pixiv_search_cache(cache_key)
    if cached is not None:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.illust_follow(restrict=restrict, offset=offset)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_search_cache(cache_key, result)
    return result


# ── Image proxy ───────────────────────────────────────────────────────


@_browse_router.get("/image-proxy")
async def image_proxy(
    request: Request,
    url: str = Query(...),
    auth: dict = Depends(require_auth),
):
    """
    Proxy pximg.net images through the server (bypasses CORS/hotlink block).
    Domain whitelist: i.pximg.net, i-f.pximg.net, s.pximg.net.
    Cached 24h in Redis.
    """
    if not _is_private(get_client_ip(request)):
        await check_rate_limit(f"img_proxy:pixiv:{auth['user_id']}", max_requests=120, window=60)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")

    host = parsed.hostname or ""
    if host not in _ALLOWED_PXIMG_HOSTS:
        raise HTTPException(
            status_code=403,
            detail=f"URL domain not allowed. Allowed: {', '.join(sorted(_ALLOWED_PXIMG_HOSTS))}",
        )

    url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
    cached_bytes = await cache.get_pixiv_image_cache(url_hash)
    if cached_bytes:
        media_type = _detect_media_type(cached_bytes)
        return Response(
            content=cached_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    try:
        client = await _make_client()
    except HTTPException:
        # Anonymous fallback — pximg.net only checks Referer, not auth tokens
        async with browser_client(timeout=30, follow_redirects=True) as http:
            try:
                resp = await http.get(url, headers=_pximg_headers())
                resp.raise_for_status()
                image_bytes = resp.content
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")
        media_type = _detect_media_type(image_bytes)
        if len(image_bytes) <= 5 * 1024 * 1024:
            await cache.set_pixiv_image_cache(url_hash, image_bytes)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    async with client:
        try:
            image_bytes, media_type = await client.download_image(url)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    if len(image_bytes) <= 5 * 1024 * 1024:
        await cache.set_pixiv_image_cache(url_hash, image_bytes)
    else:
        logger.debug("[pixiv_proxy] skipping Redis cache for large image (%d bytes): %s", len(image_bytes), url)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )
