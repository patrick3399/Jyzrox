"""E-Hentai / ExHentai API proxy endpoints."""

import hashlib
import json
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.redis_client import eh_semaphore, get_redis
from services import cache
from services.cache import push_system_alert
from services.credential import get_credential
from services.eh_client import EhClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["e-hentai"])


async def _make_client() -> EhClient:
    """Load EH cookies from DB and return a configured client (guest if no creds)."""
    cred_json = await get_credential("ehentai")
    cookies = json.loads(cred_json) if cred_json else {}
    return EhClient(cookies=cookies)


# ── Search ───────────────────────────────────────────────────────────

@router.get("/search")
async def search(
    q: str = Query(default=""),
    page: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    _: dict = Depends(require_auth),
):
    """Search E-Hentai galleries (scrape + gdata batch)."""
    cache_key = f"eh:search:{q}:{page}:{category}"
    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.search(query=q, page=page, category=category)
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, result, 300)
    return result


# ── Gallery metadata ─────────────────────────────────────────────────

@router.get("/gallery/{gid}/{token}")
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
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_gallery_cache(gid, metadata)
    return JSONResponse(
        content=metadata,
        headers={"Cache-Control": "private, max-age=3600"},  # 1h browser cache
    )


# ── Preview thumbnails (lightweight — single page scrape) ────────────

@router.get("/gallery/{gid}/{token}/previews")
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
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    str_previews = {str(k): v for k, v in preview_map.items()}
    await cache.set_preview_cache(gid, str_previews)
    return JSONResponse(
        content={"gid": gid, "previews": str_previews},
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ── Image token list ─────────────────────────────────────────────────

@router.get("/gallery/{gid}/{token}/images")
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


# ── Image proxy ──────────────────────────────────────────────────────

@router.get("/image-proxy/{gid}/{page}")
async def image_proxy(
    gid: int,
    page: int,
    _: dict = Depends(require_auth),
):
    """
    Proxy a gallery image through the server.

    Flow:
      1. Check Redis cache (TTL 24h) — return if hit
      2. Look up image page token from imagelist cache
      3. Acquire global EH semaphore (max EH_MAX_CONCURRENCY)
      4. Fetch image page HTML → extract image URL
      5. Fetch image bytes → cache → return
    """
    # 1. Cache hit
    cached_bytes = await cache.get_proxied_image(gid, page)
    if cached_bytes:
        from services.eh_client import _detect_media_type
        return Response(
            content=cached_bytes,
            media_type=_detect_media_type(cached_bytes),
            headers={"Cache-Control": "private, max-age=86400"},  # 24h
        )

    # 2. Resolve image page token
    token_map = await cache.get_imagelist_cache(gid)
    if not token_map:
        raise HTTPException(
            status_code=404,
            detail="Image token list not in cache. Call /api/eh/gallery/{gid}/{token}/images first.",
        )
    image_page_token = token_map.get(str(page))
    if not image_page_token:
        raise HTTPException(status_code=404, detail=f"Page {page} not in gallery {gid}")

    # 3–5. Fetch under semaphore
    client = await _make_client()
    async with client:
        try:
            async with eh_semaphore.acquire():
                image_url = await client.get_image_url(image_page_token, gid, page)
                image_bytes, media_type = await client.fetch_image_bytes(image_url)
        except TimeoutError:
            raise HTTPException(status_code=503, detail="EH semaphore timeout")
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")

    await cache.set_proxied_image(gid, page, image_bytes)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── Favorites ─────────────────────────────────────────────────────────

@router.get("/favorites")
async def get_favorites(
    favcat: str = Query(default="all"),
    q: str = Query(default=""),
    next: str = Query(default="", alias="next"),
    prev: str = Query(default="", alias="prev"),
    _: dict = Depends(require_auth),
):
    """Browse EH cloud favorites with cursor-based pagination."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise HTTPException(status_code=400, detail="EH credentials not configured")

    cache_key = f"eh:favorites:{favcat}:{next}:{prev}:{q}"
    cached = await cache.get_json(cache_key)
    if cached:
        return cached

    client = await _make_client()
    async with client:
        try:
            result = await client.get_favorites(
                favcat=favcat, search=q,
                next_cursor=next, prev_cursor=prev,
            )
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    await cache.set_json(cache_key, result, 120)  # 2min cache — favorites change often
    return result


# ── Thumbnail proxy ───────────────────────────────────────────────────

_ALLOWED_THUMB_HOSTS = {"ehgt.org", "e-hentai.org", "exhentai.org", "ul.ehgt.org"}


@router.get("/thumb-proxy")
async def thumb_proxy(
    url: str,
    _: dict = Depends(require_auth),
):
    """Proxy EH thumbnail CDN images so the frontend never calls external URLs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")
    host = parsed.hostname or ""
    # Allow exact match or subdomain of allowed hosts
    if not any(host == h or host.endswith(f".{h}") for h in _ALLOWED_THUMB_HOSTS):
        raise HTTPException(status_code=403, detail="URL domain not allowed")

    cache_key = f"thumb:cdn:{hashlib.md5(url.encode()).hexdigest()}"
    cached_bytes = await get_redis().get(cache_key)
    if cached_bytes:
        return Response(
            content=cached_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=604800, immutable"},  # 7d
        )

    cred_json = await get_credential("ehentai")
    cookies = json.loads(cred_json) if cred_json else {}

    try:
        async with httpx.AsyncClient(cookies=cookies, timeout=15) as client:
            resp = await client.get(url, headers={"Referer": "https://e-hentai.org/"})
            resp.raise_for_status()
            content = resp.content
            media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Thumbnail fetch failed: {exc}")

    await get_redis().setex(cache_key, 86400, content)  # 24h
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"},  # 7d browser cache
    )
