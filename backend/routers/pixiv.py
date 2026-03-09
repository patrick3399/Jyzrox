"""Pixiv API proxy endpoints."""

import hashlib
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.errors import api_error, parse_accept_language
from services import cache
from services.credential import get_credential
from services.pixiv_client import PixivClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pixiv"])

_ALLOWED_PXIMG_HOSTS = {"i.pximg.net", "i-f.pximg.net", "s.pximg.net"}


def _locale(request: Request) -> str:
    return parse_accept_language(request.headers.get("accept-language"))


# ── Client factory ────────────────────────────────────────────────────


async def _make_client(locale: str = "en") -> PixivClient:
    """Load Pixiv refresh_token from DB credentials and return a client."""
    refresh_token = await get_credential("pixiv")
    if not refresh_token:
        raise api_error(400, "pixiv_not_configured", locale)
    return PixivClient(refresh_token=refresh_token)


# ── Search ────────────────────────────────────────────────────────────


@router.get("/search")
async def search_illust(
    request: Request,
    word: str = Query(..., min_length=1),
    sort: str = Query(default="date_desc"),
    search_target: str = Query(default="partial_match_for_tags"),
    duration: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Search Pixiv illustrations (cached 5min)."""
    cache_key = f"{word}:{sort}:{search_target}:{duration}:{offset}"
    cached = await cache.get_pixiv_search_cache(cache_key)
    if cached is not None:
        return cached

    client = await _make_client(_locale(request))
    async with client:
        try:
            result = await client.search_illust(
                word=word,
                sort=sort,
                search_target=search_target,
                duration=duration,
                offset=offset,
            )
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid", _locale(request))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_search_cache(cache_key, result)
    return result


# ── Illust detail ─────────────────────────────────────────────────────


@router.get("/illust/{illust_id}")
async def get_illust(
    request: Request,
    illust_id: int,
    _: dict = Depends(require_auth),
):
    """Get illustration detail (cached 1h)."""
    cached = await cache.get_pixiv_illust_cache(illust_id)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    client = await _make_client(_locale(request))
    async with client:
        try:
            result = await client.illust_detail(illust_id)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid", _locale(request))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_illust_cache(illust_id, result)
    return JSONResponse(
        content=result,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ── User detail ───────────────────────────────────────────────────────


@router.get("/user/{user_id}")
async def get_user(
    request: Request,
    user_id: int,
    _: dict = Depends(require_auth),
):
    """Get user profile info + recent works (cached 30min)."""
    cached = await cache.get_pixiv_user_cache(user_id)
    if cached is not None:
        return cached

    client = await _make_client(_locale(request))
    async with client:
        try:
            user_info = await client.user_detail(user_id)
            recent = await client.user_illusts(user_id, offset=0)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid", _locale(request))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    result = {
        "user": user_info,
        "recent_illusts": recent.get("illusts", [])[:18],
    }
    await cache.set_pixiv_user_cache(user_id, result)
    return result


# ── User illusts ─────────────────────────────────────────────────────


@router.get("/user/{user_id}/illusts")
async def get_user_illusts(
    request: Request,
    user_id: int,
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Get paginated user illustrations (cached 5min)."""
    cache_key = f"user_illusts:{user_id}:{offset}"
    cached = await cache.get_pixiv_search_cache(cache_key)
    if cached is not None:
        return cached

    client = await _make_client(_locale(request))
    async with client:
        try:
            result = await client.user_illusts(user_id, offset=offset)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid", _locale(request))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_search_cache(cache_key, result)
    return result


# ── User bookmarks ───────────────────────────────────────────────────


@router.get("/user/{user_id}/bookmarks")
async def get_user_bookmarks(
    user_id: int,
    restrict: str = Query(default="public"),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Get user public bookmarks (cached 5min)."""
    cache_key = f"user_bookmarks:{user_id}:{restrict}:{offset}"
    cached = await cache.get_pixiv_search_cache(cache_key)
    if cached is not None:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.user_bookmarks(user_id, restrict=restrict, offset=offset)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_search_cache(cache_key, result)
    return result


# ── Following feed ───────────────────────────────────────────────────


@router.get("/following/feed")
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


@router.get("/image-proxy")
async def image_proxy(
    url: str = Query(...),
    _: dict = Depends(require_auth),
):
    """
    Proxy pximg.net images through the server (bypasses CORS/hotlink block).
    Domain whitelist: i.pximg.net, i-f.pximg.net, s.pximg.net.
    Cached 24h in Redis.
    """
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

    client = await _make_client()
    async with client:
        try:
            image_bytes, media_type = await client.download_image(url)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    await cache.set_pixiv_image_cache(url_hash, image_bytes)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


# ── Media type detection ──────────────────────────────────────────────


def _detect_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
