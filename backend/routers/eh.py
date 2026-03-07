"""E-Hentai / ExHentai API proxy endpoints."""

import hashlib
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from core.auth import require_auth
from core.redis_client import eh_semaphore, get_redis
from services import cache
from services.cache import push_system_alert
from services.credential import get_credential
from services.eh_client import EhClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eh", tags=["e-hentai"])


async def _make_client() -> EhClient:
    """Load EH cookies from DB and return a configured client (not yet entered)."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise HTTPException(status_code=503, detail="E-Hentai credentials not configured")
    return EhClient(cookies=json.loads(cred_json))


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

    await cache.set_json(cache_key, result, 300)
    return result


# ── Gallery metadata ─────────────────────────────────────────────────

@router.get("/gallery/{gid}/{token}")
async def get_gallery(
    gid: int,
    token: str,
    _: dict = Depends(require_auth),
):
    """Get gallery metadata via gdata API (cached 1h)."""
    cached = await cache.get_gallery_cache(gid)
    if cached:
        return cached

    client = await _make_client()
    async with client:
        try:
            metadata = await client.get_gallery_metadata(gid, token)
        except PermissionError:
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")

    await cache.set_gallery_cache(gid, metadata)
    return metadata


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
        return {"gid": gid, "images": token_map}

    # Need total page count — check gallery cache first
    gallery = await cache.get_gallery_cache(gid)
    if not gallery:
        client = await _make_client()
        async with client:
            gallery = await client.get_gallery_metadata(gid, token)
        await cache.set_gallery_cache(gid, gallery)

    total_pages = gallery["pages"]
    client = await _make_client()
    async with client:
        raw_map = await client.get_image_tokens(gid, token, total_pages)

    str_map = {str(k): v for k, v in raw_map.items()}
    await cache.set_imagelist_cache(gid, str_map)
    return {"gid": gid, "images": str_map}


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
        return Response(content=cached_bytes, media_type=_detect_media_type(cached_bytes))

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
    return Response(content=image_bytes, media_type=media_type)


# ── Thumbnail proxy ───────────────────────────────────────────────────

@router.get("/thumb-proxy")
async def thumb_proxy(
    url: str,
    _: dict = Depends(require_auth),
):
    """Proxy EH thumbnail CDN images so the frontend never calls external URLs."""
    cache_key = f"thumb:cdn:{hashlib.md5(url.encode()).hexdigest()}"
    cached_bytes = await get_redis().get(cache_key)
    if cached_bytes:
        return Response(content=cached_bytes, media_type="image/jpeg")

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
    return Response(content=content, media_type=media_type)
