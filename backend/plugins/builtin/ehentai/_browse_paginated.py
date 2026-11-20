"""E-Hentai browse routes: paginated image token list."""

import asyncio
import logging

import httpx
from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.errors import api_error
from core.redis_client import eh_semaphore
from plugins.builtin.ehentai._browse_common import _browse_router, _make_client
from services import cache
from services.cache import push_system_alert
from services.eh_client import EhClient

logger = logging.getLogger(__name__)

# EH gallery detail pages list 20 image thumbnails each.
THUMBS_PER_DETAIL = 20


async def _fetch_detail_page_tokens(
    client: EhClient, gid: int, gallery_token: str, dp: int
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Fetch one EH gallery detail page and parse its pTokens/previews.

    Writes the result to the per-detail-page cache ``eh:imgpage:{gid}:{dp}``
    (TTL 24 h) and returns ``(tokens, previews)`` keyed by str page number.
    Raises PermissionError / httpx.HTTPError / ValueError like other client
    calls; callers map those to HTTP responses.
    """
    url_html = f"{client.base_url}/g/{gid}/{gallery_token}/?p={dp}"
    resp = await client._http_get(url_html)
    resp.raise_for_status()
    client._check_auth(resp.text, resp)

    page_tokens, page_previews = client._parse_detail_html(resp.text)
    str_tokens = {str(k): v for k, v in page_tokens.items()}
    str_prevs = {str(k): v for k, v in page_previews.items()}
    await cache.set_json(f"eh:imgpage:{gid}:{dp}", {"tokens": str_tokens, "previews": str_prevs}, 86400)
    return str_tokens, str_prevs


@_browse_router.get("/gallery/{gid}/{token}/images-paginated")
async def get_gallery_images_paginated(
    gid: int,
    token: str,
    start_page: int = Query(0, ge=0, description="0-based index of the first image"),
    count: int = Query(20, ge=1, le=100, description="Number of images to return"),
    _: dict = Depends(require_auth),
):
    """
    Return pTokens and preview thumbnails for a single window of images.

    Unlike /images (which fetches all pages upfront), this endpoint makes only
    the one or two EH detail-page HTTP requests needed for the requested window.
    Suitable for lazy-loading large galleries page by page.

    Cache key: ``eh:imgpage:{gid}:{detail_page}`` (per EH detail page, TTL 24 h).
    Returns: {gid, images: [{page, token}], previews: {page: url}, has_more, total}
    """
    # Resolve total page count — gallery cache first.
    gallery = await cache.get_gallery_cache(gid)
    if not gallery:
        client = await _make_client()
        async with client:
            try:
                gallery = await client.get_gallery_metadata(gid, token)
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
        await cache.set_gallery_cache(gid, gallery)

    total_pages: int = gallery["pages"]

    # Clamp check before any network work.
    if total_pages == 0 or start_page >= total_pages:
        return JSONResponse(
            content={"gid": gid, "images": [], "previews": {}, "has_more": False, "total": total_pages},
            headers={"Cache-Control": "private, max-age=86400"},
        )

    end_page_excl = min(start_page + count, total_pages)
    first_dp = start_page // THUMBS_PER_DETAIL
    last_dp = (end_page_excl - 1) // THUMBS_PER_DETAIL

    # Check per-detail-page Redis cache before making HTTP requests.
    token_map: dict[str, str] = {}
    preview_map: dict[str, str] = {}
    missing_dps: list[int] = []

    for dp in range(first_dp, last_dp + 1):
        ck = f"eh:imgpage:{gid}:{dp}"
        cached_dp = await cache.get_json(ck)
        if cached_dp:
            token_map.update(cached_dp.get("tokens", {}))
            preview_map.update(cached_dp.get("previews", {}))
        else:
            missing_dps.append(dp)

    if missing_dps:
        import httpx as _httpx

        client = await _make_client()
        async with client:
            try:
                for i, dp in enumerate(missing_dps):
                    if i > 0:
                        await asyncio.sleep(0.3)

                    str_tokens, str_prevs = await _fetch_detail_page_tokens(client, gid, token, dp)
                    token_map.update(str_tokens)
                    preview_map.update(str_prevs)

            except PermissionError as e:
                detail = str(e)
                await push_system_alert(detail)
                if "509" in detail:
                    raise api_error(403, "eh_bandwidth_exceeded", "en")
                if "Sad Panda" in detail:
                    raise api_error(403, "eh_access_denied", "en")
                raise api_error(401, "eh_cookie_invalid", "en")
            except _httpx.HTTPError as e:
                logger.error("Failed to fetch image tokens for %s dp=%s: %s", gid, missing_dps, e)
                raise HTTPException(status_code=502, detail=f"EH request failed: {e}")
            except ValueError as e:
                raise HTTPException(status_code=503, detail=str(e))

    # Build ordered result list for the requested window.
    images = []
    for img_idx in range(start_page, end_page_excl):
        page_num = img_idx + 1  # EH page numbers are 1-based
        pt = token_map.get(str(page_num))
        if pt:
            images.append({"page": page_num, "token": pt})

    # Keep only previews inside the requested window.
    window_previews = {k: v for k, v in preview_map.items() if start_page + 1 <= int(k) <= end_page_excl}

    # Merge tokens into imagelist:{gid} so image-proxy can resolve them.
    existing = await cache.get_imagelist_cache(gid) or {}
    existing.update({str(img["page"]): img["token"] for img in images})
    await cache.set_imagelist_cache(gid, existing)

    # Merge previews into preview cache for consistency.
    existing_prev = await cache.get_preview_cache(gid) or {}
    existing_prev.update(window_previews)
    await cache.set_preview_cache(gid, existing_prev)

    return JSONResponse(
        content={
            "gid": gid,
            "images": images,
            "previews": window_previews,
            "has_more": end_page_excl < total_pages,
            "total": total_pages,
        },
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── Image proxy ──────────────────────────────────────────────────────


async def _resolve_ptoken_on_demand(gid: int, page: int) -> str | None:
    """
    Resolve a single missing pToken (EhViewer ``getPTokenFromInternet`` pattern).

    A distant page jump can hit /image-proxy before the frontend's sequential
    prefetch has populated ``imagelist:{gid}``.  Instead of failing, locate the
    EH detail page that lists ``page``, reuse the ``eh:imgpage:{gid}:{dp}``
    cache when possible, and otherwise fetch that one detail page under the
    global EH semaphore.  Returns None when the token cannot be resolved
    (notably when the gallery cache — and thus the gallery token — is absent).
    """
    if page < 1:
        return None
    dp = (page - 1) // THUMBS_PER_DETAIL

    cached_dp = await cache.get_json(f"eh:imgpage:{gid}:{dp}")
    if cached_dp:
        return cached_dp.get("tokens", {}).get(str(page))

    gallery = await cache.get_gallery_cache(gid)
    gallery_token = (gallery or {}).get("token")
    if not gallery_token:
        return None

    client = await _make_client()
    async with client:
        try:
            async with eh_semaphore.acquire():
                tokens, _ = await _fetch_detail_page_tokens(client, gid, gallery_token, dp)
        except TimeoutError:
            raise HTTPException(status_code=503, detail="EH semaphore timeout")
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", "en")
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", "en")
            raise api_error(401, "eh_cookie_invalid", "en")
        except httpx.HTTPError as e:
            logger.error("On-demand pToken fetch failed for %s p=%s dp=%s: %s", gid, page, dp, e)
            raise HTTPException(status_code=502, detail=f"EH request failed: {e}")
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))

    # Merge into imagelist:{gid} so neighbouring pages resolve without refetch.
    existing = await cache.get_imagelist_cache(gid) or {}
    existing.update(tokens)
    await cache.set_imagelist_cache(gid, existing)

    return tokens.get(str(page))
