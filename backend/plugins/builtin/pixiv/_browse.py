"""Pixiv browse plugin — provides the Browsable protocol and browse endpoints."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.errors import api_error, parse_accept_language
from core.rate_limit import check_rate_limit
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
from services.credential import get_credential
from services.pixiv_client import PixivClient

logger = logging.getLogger(__name__)

_ALLOWED_PXIMG_HOSTS = {"i.pximg.net", "i-f.pximg.net", "s.pximg.net"}


# ---------------------------------------------------------------------------
# PixivBrowsePlugin class
# ---------------------------------------------------------------------------


class PixivBrowsePlugin(BrowsePlugin):
    """BrowsePlugin + Browsable for Pixiv."""

    meta = PluginMeta(
        name="Pixiv",
        source_id="pixiv",
        version="1.0.0",
        description="Pixiv artwork browser",
        url_patterns=["pixiv.net"],
        credential_schema=[
            FieldDef(
                name="refresh_token",
                field_type="password",
                label="Refresh Token",
                required=True,
            ),
        ],
        supported_sites=[
            SiteInfo(domain="pixiv.net", name="Pixiv", source_id="pixiv", category="art", has_tags=True),
        ],
        concurrency=4,
        semaphore_key="pixiv",
    )

    def browse_schema(self) -> BrowseSchema:
        return BrowseSchema(
            search_fields=[
                FieldDef(name="word", field_type="text", label="Search keyword", required=True, placeholder="character name, tag..."),
                FieldDef(name="sort", field_type="select", label="Sort"),
                FieldDef(name="search_target", field_type="select", label="Search target"),
                FieldDef(name="duration", field_type="select", label="Duration"),
            ],
            supports_favorites=True,
            supports_popular=True,
        )

    async def search(self, params: dict, credentials: dict | None = None) -> SearchResult:
        """Run a Pixiv search through PixivClient."""
        refresh_token = ""
        if credentials:
            if isinstance(credentials, str):
                refresh_token = credentials
            elif isinstance(credentials, dict):
                refresh_token = credentials.get("refresh_token", "")

        if not refresh_token:
            return SearchResult(galleries=[], total=0)

        async with PixivClient(refresh_token) as client:
            result = await client.search_illust(
                word=params.get("word", ""),
                sort=params.get("sort", "date_desc"),
                search_target=params.get("search_target", "partial_match_for_tags"),
                duration=params.get("duration"),
                offset=int(params.get("offset", 0)),
            )

        illusts = result.get("illusts", [])
        return SearchResult(
            galleries=[{"illust": i} for i in illusts],
            total=len(illusts),
            has_next=bool(result.get("next_url")),
        )

    async def proxy_image(self, url: str, credentials: dict | None = None) -> tuple[bytes, str]:
        """Fetch image bytes via PixivClient for proxying."""
        refresh_token = ""
        if credentials:
            if isinstance(credentials, str):
                refresh_token = credentials
            elif isinstance(credentials, dict):
                refresh_token = credentials.get("refresh_token", "")

        async with PixivClient(refresh_token) as client:
            image_bytes, media_type = await client.download_image(url)
        return image_bytes, media_type

    # ------------------------------------------------------------------
    # CredentialProvider protocol
    # ------------------------------------------------------------------

    def credential_flows(self) -> list[CredentialFlow]:
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows
        return pixiv_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential
        return await verify_pixiv_credential(credentials)

    # ------------------------------------------------------------------
    # Browsable protocol method
    # ------------------------------------------------------------------

    def get_browse_router(self) -> APIRouter:
        """Return the Pixiv browse router."""
        return _browse_router


# ---------------------------------------------------------------------------
# Browse router — formerly routers/pixiv.py
# ---------------------------------------------------------------------------

_browse_router = APIRouter(tags=["pixiv"])


def _locale(request: Request) -> str:
    return parse_accept_language(request.headers.get("accept-language"))


# ── Client factory ────────────────────────────────────────────────────


async def _make_client(locale: str = "en") -> PixivClient:
    """Load Pixiv refresh_token from DB credentials and return a client."""
    refresh_token = await get_credential("pixiv")
    if not refresh_token:
        raise api_error(400, "pixiv_not_configured", locale)
    return PixivClient(refresh_token=refresh_token)


# ── Media type detection ──────────────────────────────────────────────


def _detect_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


# ── Ranking ───────────────────────────────────────────────────────────


@_browse_router.get("/ranking")
async def get_ranking(
    mode: str = Query(default="daily"),
    content: str = Query(default="all"),
    date: str | None = Query(default=None, description="YYYYMMDD"),
    page: int = Query(default=1, ge=1),
    _: dict = Depends(require_auth),
):
    """Get Pixiv public ranking (no Pixiv credentials required, cached 5min)."""
    cache_key = f"pixiv:ranking:{mode}:{content}:{date}:{page}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return cached

    params: dict = {"format": "json", "mode": mode, "content": content, "p": page}
    if date:
        params["date"] = date

    headers = {
        "Referer": "https://www.pixiv.net/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        try:
            resp = await http.get(
                "https://www.pixiv.net/ranking.php",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv ranking request failed: {e}")

    await cache.set_json(cache_key, result, 300)  # 5min
    return result


# ── Public search (no Pixiv credentials) ─────────────────────────────


@_browse_router.get("/search-public")
async def search_public(
    word: str = Query(..., min_length=1),
    order: str = Query(default="date_d", description="date_d (newest), date (oldest), popular_d (popular)"),
    mode: str = Query(default="all", description="all, safe, r18"),
    page: int = Query(default=1, ge=1),
    s_mode: str = Query(default="s_tag", description="s_tag (partial), s_tag_full (exact), s_tc (title/caption)"),
    type: str = Query(default="all", description="all, illust, manga, ugoira"),
    _: dict = Depends(require_auth),
):
    """Search Pixiv artworks via public ajax API (no Pixiv credentials required, cached 5min)."""
    cache_key = f"pixiv:search_public:{word}:{order}:{mode}:{page}:{s_mode}:{type}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return cached

    params = {
        "word": word,
        "order": order,
        "mode": mode,
        "p": page,
        "s_mode": s_mode,
        "type": type,
        "lang": "en",
    }

    headers = {
        "Referer": "https://www.pixiv.net/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        try:
            resp = await http.get(
                f"https://www.pixiv.net/ajax/search/artworks/{word}",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv search request failed: {e}")

    if raw.get("error"):
        raise HTTPException(status_code=502, detail="Pixiv returned an error")

    body = raw.get("body", {})
    illust_manga = body.get("illustManga", {})
    artworks = illust_manga.get("data", [])
    total = illust_manga.get("total", 0)

    # Normalize to a format similar to the authenticated search
    illusts = []
    for item in artworks:
        illusts.append({
            "id": int(item.get("id", 0)),
            "title": item.get("title", ""),
            "image_urls": {
                "square_medium": item.get("url", ""),
                "medium": item.get("url", ""),
            },
            "user": {
                "id": int(item.get("userId", 0)),
                "name": item.get("userName", ""),
                "profile_image_urls": {
                    "medium": item.get("profileImageUrl", ""),
                },
            },
            "page_count": item.get("pageCount", 1),
            "width": item.get("width", 0),
            "height": item.get("height", 0),
            "tags": item.get("tags", []),
            "create_date": item.get("createDate", ""),
            "total_view": 0,  # not available in public API
            "total_bookmarks": 0,  # not available in public API
        })

    result = {
        "illusts": illusts,
        "total": total,
        "next_offset": page * 60 if len(artworks) >= 60 else None,
    }

    # Also include popular works if available (first page only)
    popular = body.get("popular", {})
    if popular:
        popular_recent = popular.get("recent", [])
        popular_permanent = popular.get("permanent", [])
        popular_illusts = []
        for item in (popular_permanent + popular_recent):
            popular_illusts.append({
                "id": int(item.get("id", 0)),
                "title": item.get("title", ""),
                "image_urls": {
                    "square_medium": item.get("url", ""),
                    "medium": item.get("url", ""),
                },
                "user": {
                    "id": int(item.get("userId", 0)),
                    "name": item.get("userName", ""),
                    "profile_image_urls": {
                        "medium": item.get("profileImageUrl", ""),
                    },
                },
                "page_count": item.get("pageCount", 1),
                "width": item.get("width", 0),
                "height": item.get("height", 0),
                "tags": item.get("tags", []),
                "create_date": item.get("createDate", ""),
                "total_view": 0,
                "total_bookmarks": 0,
            })
        if popular_illusts:
            result["popular"] = popular_illusts

    related_tags = body.get("relatedTags", [])
    if related_tags:
        result["related_tags"] = related_tags

    await cache.set_json(cache_key, result, 300)  # 5min
    return result


# ── Search ────────────────────────────────────────────────────────────


@_browse_router.get("/search")
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


async def _fetch_illust_public(illust_id: int) -> dict:
    """Fetch illust detail via Pixiv public ajax API (no credentials required)."""
    headers = {
        "Referer": "https://www.pixiv.net/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        try:
            resp = await http.get(
                f"https://www.pixiv.net/ajax/illust/{illust_id}",
                headers=headers,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")

    if raw.get("error"):
        msg = raw.get("message", "Pixiv returned an error")
        raise HTTPException(status_code=404, detail=msg)

    body = raw.get("body", {})
    tags_data = body.get("tags", {}).get("tags", [])

    # Also try to fetch pages info
    pages: list = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            pages_resp = await http.get(
                f"https://www.pixiv.net/ajax/illust/{illust_id}/pages",
                headers=headers,
            )
            if pages_resp.status_code == 200:
                pages_raw = pages_resp.json()
                if not pages_raw.get("error"):
                    pages = pages_raw.get("body", [])
    except httpx.HTTPError:
        pass  # Pages info is optional

    # Build image_urls from body urls
    urls = body.get("urls", {})
    image_urls = {
        "square_medium": urls.get("mini", ""),
        "medium": urls.get("small", ""),
        "large": urls.get("regular", ""),
    }
    if urls.get("original"):
        image_urls["original"] = urls["original"]

    # Build meta_pages from pages API
    meta_pages = []
    for p in pages:
        p_urls = p.get("urls", {})
        meta_pages.append({
            "image_urls": {
                "square_medium": p_urls.get("thumb_mini", ""),
                "medium": p_urls.get("small", ""),
                "large": p_urls.get("regular", ""),
                "original": p_urls.get("original", ""),
            }
        })

    # Normalize to same format as authenticated API response
    result = {
        "id": illust_id,
        "title": body.get("title", ""),
        "caption": body.get("description", ""),
        "image_urls": image_urls,
        "user": {
            "id": int(body.get("userId", 0)),
            "name": body.get("userName", ""),
            "profile_image_urls": {
                "medium": (
                    body.get("userIllusts", {}).get(str(illust_id), {}).get("profileImageUrl", "")
                    if body.get("userIllusts")
                    else ""
                ),
            },
        },
        "page_count": body.get("pageCount", 1),
        "width": body.get("width", 0),
        "height": body.get("height", 0),
        "tags": [tag.get("tag", "") for tag in tags_data],
        "create_date": body.get("createDate", ""),
        "total_view": body.get("viewCount", 0),
        "total_bookmarks": body.get("bookmarkCount", 0),
        "total_comments": body.get("commentCount", 0),
        "type": body.get("illustType", 0),  # 0=illust, 1=manga, 2=ugoira
        "meta_pages": meta_pages,
        "meta_single_page": (
            {"original_image_url": urls.get("original", "")}
            if body.get("pageCount", 1) == 1
            else {}
        ),
    }

    return result


@_browse_router.get("/illust/{illust_id}")
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

    # Try authenticated client first; fall back to public ajax API
    refresh_token = await get_credential("pixiv")
    if refresh_token:
        client = PixivClient(refresh_token=refresh_token)
        async with client:
            try:
                result = await client.illust_detail(illust_id)
            except PermissionError:
                raise api_error(401, "pixiv_token_invalid", _locale(request))
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"Pixiv request failed: {e}")
    else:
        # Fallback: public ajax API (no credentials needed)
        result = await _fetch_illust_public(illust_id)

    await cache.set_pixiv_illust_cache(illust_id, result)
    return JSONResponse(
        content=result,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ── User detail ───────────────────────────────────────────────────────


@_browse_router.get("/user/{user_id}")
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


@_browse_router.get("/user/{user_id}/illusts")
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


@_browse_router.get("/user/{user_id}/bookmarks")
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


@_browse_router.get("/bookmarks")
async def get_my_bookmarks(
    restrict: str = Query(default="public"),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """Get the currently authenticated user's bookmarks (cached 5min)."""
    cache_key = f"my_bookmarks:{restrict}:{offset}"
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

            result = await client.user_bookmarks(user_id, restrict=restrict, offset=offset)
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
    url: str = Query(...),
    auth: dict = Depends(require_auth),
):
    """
    Proxy pximg.net images through the server (bypasses CORS/hotlink block).
    Domain whitelist: i.pximg.net, i-f.pximg.net, s.pximg.net.
    Cached 24h in Redis.
    """
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
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            try:
                resp = await http.get(url, headers={"Referer": "https://www.pixiv.net/"})
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
