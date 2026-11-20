"""E-Hentai browse routes: thumbnail proxy."""

import asyncio
import hashlib
import json
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException, Request, Response

from core.auth import require_auth
from core.client_identity import browser_headers
from core.rate_limit import _is_private, check_rate_limit, get_client_ip
from plugins.builtin.ehentai._browse_common import _browse_router
from services import cache
from services.browser_http import browser_client
from services.credential import get_credential

_thumb_semaphore = asyncio.Semaphore(4)
_ALLOWED_THUMB_HOSTS = {"ehgt.org", "e-hentai.org", "exhentai.org", "s.exhentai.org", "ul.ehgt.org", "hath.network"}


@_browse_router.get("/thumb-proxy")
async def thumb_proxy(
    request: Request,
    url: str,
    auth: dict = Depends(require_auth),
):
    """Proxy EH thumbnail CDN images so the frontend never calls external URLs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")
    host = parsed.hostname or ""
    if not any(host == h or host.endswith(f".{h}") for h in _ALLOWED_THUMB_HOSTS):
        raise HTTPException(status_code=403, detail="URL domain not allowed")

    # Rewrite slow ExH CDN URLs to faster ehgt.org CDN.
    # s.exhentai.org and exhentai.org thumbnails are mirrored on ehgt.org.
    if host and "exhentai" in host:
        from urllib.parse import urlunparse

        url = urlunparse(parsed._replace(scheme="https", netloc="ehgt.org"))
        parsed = urlparse(url)  # re-parse for the referer logic below

    url_hash = hashlib.md5(url.encode()).hexdigest()
    cached_bytes = await cache.get_cdn_thumb(url_hash)
    if cached_bytes:
        return Response(
            content=cached_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=604800, immutable"},  # 7d
        )

    # Rate-limit the outbound CDN call, not the request. The budget exists to keep
    # us from hammering the EH CDN, so only a cache miss — the one branch that
    # actually leaves our network — spends it. Charging cache hits made a 50-tile
    # browse page burn the whole 120/min budget in under three pages of scrolling.
    if not _is_private(get_client_ip(request)):
        await check_rate_limit(f"img_proxy:eh_thumb:{auth['user_id']}", max_requests=600, window=60)

    cred_json = await get_credential("ehentai")
    cookies = json.loads(cred_json) if cred_json else {}

    async with _thumb_semaphore:
        try:
            referer = "https://exhentai.org/" if "exhentai" in (parsed.hostname or "") else "https://e-hentai.org/"
            async with browser_client(cookies=cookies, timeout=30) as client:
                resp = await client.get(url, headers=browser_headers("image", site="cross-site", referer=referer))
                resp.raise_for_status()
                content = resp.content
                media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Thumbnail fetch failed: {exc}")

    await cache.set_cdn_thumb(url_hash, content)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"},  # 7d browser cache
    )
