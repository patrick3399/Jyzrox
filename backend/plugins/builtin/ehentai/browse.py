"""E-Hentai BrowsePlugin.

Provides a generic plugin interface over the existing EhClient.  The browse
endpoints previously in routers/eh.py are now owned by this module and
exposed via get_browse_router().
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from core.auth import require_auth
from core.config import settings as app_settings
from core.errors import api_error, parse_accept_language
from core.database import async_session
from core.rate_limit import check_rate_limit, get_client_ip, _is_private
from core.redis_client import eh_semaphore, get_redis
from db.models import BlockedTag
from plugins.base import BrowsePlugin
from plugins.models import (
    BrowseSchema,
    CredentialFlow,
    CredentialStatus,
    FieldDef,
    PluginMeta,
    SearchResult,
    SiteInfo,
)
from services import cache
from services.cache import push_system_alert
from services.credential import get_credential
from services.eh_client import EhClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EhBrowsePlugin class
# ---------------------------------------------------------------------------


class EhBrowsePlugin(BrowsePlugin):
    """BrowsePlugin for E-Hentai / ExHentai."""

    meta = PluginMeta(
        name="E-Hentai",
        source_id="ehentai",
        version="1.0.0",
        description="E-Hentai / ExHentai gallery downloader",
        url_patterns=["e-hentai.org", "exhentai.org"],
        credential_schema=[
            FieldDef(
                name="ipb_member_id",
                field_type="text",
                label="ipb_member_id",
                required=True,
                placeholder="12345",
            ),
            FieldDef(
                name="ipb_pass_hash",
                field_type="password",
                label="ipb_pass_hash",
                required=True,
                placeholder="",
            ),
            FieldDef(
                name="sk",
                field_type="password",
                label="sk",
                required=False,
                placeholder="",
            ),
            FieldDef(
                name="igneous",
                field_type="password",
                label="igneous (ExHentai)",
                required=False,
                placeholder="",
            ),
        ],
        supported_sites=[
            SiteInfo(domain="e-hentai.org", name="E-Hentai", source_id="ehentai", category="gallery", has_tags=True),
            SiteInfo(domain="exhentai.org", name="ExHentai", source_id="ehentai", category="gallery", has_tags=True),
        ],
        concurrency=3,
        semaphore_key="ehentai",
    )

    def browse_schema(self) -> BrowseSchema:
        return BrowseSchema(
            search_fields=[
                FieldDef(name="q", field_type="text", label="Search query", placeholder="artist:..., tag:..."),
                FieldDef(name="category", field_type="text", label="Category", placeholder="Doujinshi"),
                FieldDef(name="f_cats", field_type="text", label="Category bitmask (f_cats)"),
                FieldDef(name="advance", field_type="select", label="Advanced search"),
                FieldDef(name="adv_search", field_type="text", label="adv_search flags"),
                FieldDef(name="min_rating", field_type="text", label="Minimum rating (2-5)"),
                FieldDef(name="page_from", field_type="text", label="Min pages"),
                FieldDef(name="page_to", field_type="text", label="Max pages"),
                FieldDef(name="language", field_type="text", label="Language tag"),
            ],
            supports_favorites=True,
            supports_popular=True,
            supports_toplist=True,
        )

    async def search(
        self,
        params: dict,
        credentials: dict | None = None,
    ) -> SearchResult:
        """Run an EH search through EhClient."""
        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[eh_browse] malformed credentials JSON")
            else:
                cookies = credentials  # type: ignore[assignment]

        redis = get_redis()
        pref = await redis.get("setting:eh_use_ex")
        if pref is not None:
            use_ex = pref == b"1"
        else:
            use_ex = app_settings.eh_use_ex or bool(cookies.get("igneous"))

        client = EhClient(cookies=cookies, use_ex=use_ex)
        async with client:
            result = await client.search(
                query=params.get("q", ""),
                page=int(params.get("page", 0)),
                category=params.get("category"),
                f_cats=params.get("f_cats"),
                advance=bool(params.get("advance", False)),
                adv_search=int(params.get("adv_search", 0)),
                min_rating=params.get("min_rating"),
                page_from=params.get("page_from"),
                page_to=params.get("page_to"),
            )

        galleries = result.get("galleries", [])
        return SearchResult(
            galleries=galleries,
            total=result.get("total", len(galleries)),
            page=int(params.get("page", 0)),
            has_next=result.get("has_next", False),
            has_prev=result.get("has_prev", False),
            extra=result,
        )

    async def proxy_image(
        self,
        url: str,
        credentials: dict | None = None,
    ) -> tuple[bytes, str]:
        """Fetch image bytes via EhClient for proxying."""
        from services.eh_client import _detect_media_type

        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                cookies = credentials  # type: ignore[assignment]

        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=30) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            data = resp.content
            media_type = _detect_media_type(data)
            return data, media_type

    # ------------------------------------------------------------------
    # CredentialProvider protocol
    # ------------------------------------------------------------------

    def credential_flows(self) -> list[CredentialFlow]:
        from plugins.builtin.ehentai._credentials import eh_credential_flows
        return eh_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        from plugins.builtin.ehentai._credentials import verify_eh_credential
        return await verify_eh_credential(credentials)

    # ------------------------------------------------------------------
    # Browsable protocol method
    # ------------------------------------------------------------------

    def get_browse_router(self) -> APIRouter:
        """Return the EH browse router."""
        return _browse_router


# ---------------------------------------------------------------------------
# Browse router — formerly routers/eh.py
# ---------------------------------------------------------------------------

_browse_router = APIRouter(tags=["e-hentai"])


def _locale(request: Request) -> str:
    return parse_accept_language(request.headers.get("accept-language"))


# ── Blocked tag helpers ───────────────────────────────────────────────


async def _get_blocked_tags(user_id: int) -> set[str]:
    """Return set of 'namespace:name' blocked tag strings for the user."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id)
            )
        ).all()
    return {f"{r.namespace}:{r.name}" for r in rows}


def _filter_blocked(galleries: list[dict], blocked: set[str]) -> list[dict]:
    """Filter out galleries that contain any blocked tag."""
    if not blocked:
        return galleries
    return [g for g in galleries if not blocked.intersection(set(g.get("tags", [])))]


async def _make_client() -> EhClient:
    """Load EH cookies from DB and return a configured client (guest if no creds)."""
    cred_json = await get_credential("ehentai")
    cookies = json.loads(cred_json) if cred_json else {}
    redis = get_redis()
    pref = await redis.get("setting:eh_use_ex")
    if pref is not None:
        use_ex = pref == b"1"
    else:
        use_ex = app_settings.eh_use_ex or bool(cookies.get("igneous"))
    return EhClient(cookies=cookies, use_ex=use_ex)


# ── Search ───────────────────────────────────────────────────────────


@_browse_router.get("/search")
async def search(
    request: Request,
    q: str = Query(default=""),
    page: int = Query(default=0, ge=0),
    next_gid: int | None = Query(default=None),
    prev: bool = Query(default=False),
    category: str | None = Query(default=None),
    f_cats: int | None = Query(default=None),
    advance: bool = Query(default=False),
    adv_search: int = Query(default=0),
    min_rating: int | None = Query(default=None, ge=2, le=5),
    page_from: int | None = Query(default=None),
    page_to: int | None = Query(default=None),
    language: str | None = Query(default=None),
    auth: dict = Depends(require_auth),
):
    """Search E-Hentai galleries (scrape + gdata batch).

    Pagination uses EH cursor-based params: next_gid (gid of next page boundary)
    and prev (go to previous page). The legacy `page` param is kept for backward
    compatibility but is not forwarded to EH — the server ignores it.
    """
    effective_q = q
    if language:
        lang_tag = f"language:{language}"
        effective_q = f"{lang_tag} {q}".strip() if q else lang_tag

    cache_key = f"eh:search:{effective_q}:{next_gid}:{prev}:{category}:{f_cats}:{advance}:{adv_search}:{min_rating}:{page_from}:{page_to}"
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
            result = await client.search(
                query=effective_q,
                page=page,
                next_gid=next_gid,
                prev=prev,
                category=category,
                f_cats=f_cats,
                advance=advance,
                adv_search=adv_search,
                min_rating=min_rating,
                page_from=page_from,
                page_to=page_to,
            )
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

    await cache.set_json(cache_key, result, 300)

    user_id = auth["user_id"]
    blocked = await _get_blocked_tags(user_id)
    if blocked and result.get("galleries"):
        result["galleries"] = _filter_blocked(result["galleries"], blocked)

    return result


# ── Popular ──────────────────────────────────────────────────────────


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
    THUMBS_PER_DETAIL = 20

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

                    url_html = f"{client.base_url}/g/{gid}/{token}/?p={dp}"
                    resp = await client._http.get(url_html)
                    resp.raise_for_status()
                    client._check_auth(resp.text, resp)

                    page_tokens, page_previews = client._parse_detail_html(resp.text)

                    str_tokens = {str(k): v for k, v in page_tokens.items()}
                    str_prevs = {str(k): v for k, v in page_previews.items()}

                    ck = f"eh:imgpage:{gid}:{dp}"
                    await cache.set_json(ck, {"tokens": str_tokens, "previews": str_prevs}, 86400)

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
    window_previews = {
        k: v
        for k, v in preview_map.items()
        if start_page + 1 <= int(k) <= end_page_excl
    }

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
      2. Look up image page token from imagelist cache
      3. Acquire global EH semaphore (max EH_MAX_CONCURRENCY)
      4. Fetch image page HTML → extract image URL
      5. Fetch image bytes → cache → return
    """
    if not _is_private(get_client_ip(request)):
        await check_rate_limit(f"img_proxy:eh:{auth['user_id']}", max_requests=120, window=60)

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

_thumb_semaphore = asyncio.Semaphore(4)
_ALLOWED_THUMB_HOSTS = {"ehgt.org", "e-hentai.org", "exhentai.org", "ul.ehgt.org", "hath.network"}


@_browse_router.get("/thumb-proxy")
async def thumb_proxy(
    request: Request,
    url: str,
    auth: dict = Depends(require_auth),
):
    """Proxy EH thumbnail CDN images so the frontend never calls external URLs."""
    if not _is_private(get_client_ip(request)):
        await check_rate_limit(f"img_proxy:eh_thumb:{auth['user_id']}", max_requests=120, window=60)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")
    host = parsed.hostname or ""
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

    async with _thumb_semaphore:
        try:
            referer = "https://exhentai.org/" if "exhentai" in (parsed.hostname or "") else "https://e-hentai.org/"
            async with httpx.AsyncClient(cookies=cookies, timeout=30) as client:
                resp = await client.get(url, headers={"Referer": referer})
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
