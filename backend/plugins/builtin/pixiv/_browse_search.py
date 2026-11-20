"""Pixiv browse routes: ranking and search."""

import httpx
from fastapi import Depends, HTTPException, Query, Request

from core.auth import require_auth
from core.errors import api_error, parse_accept_language
from plugins.builtin.pixiv._browse_common import _ajax_headers, _browse_router, _locale, _make_client
from services import cache
from services.browser_http import browser_client

# ── Ranking ───────────────────────────────────────────────────────────

_R18_MODE_MAP = {
    "daily_r18": "day_r18",
    "weekly_r18": "week_r18",
}


@_browse_router.get("/ranking")
async def get_ranking(
    request: Request,
    mode: str = Query(default="daily"),
    content: str = Query(default="all"),
    date: str | None = Query(default=None, description="YYYYMMDD"),
    page: int = Query(default=1, ge=1),
    _: dict = Depends(require_auth),
):
    """Get Pixiv ranking. Public modes cached 5min (no credentials). R18 modes require Pixiv credentials."""
    if mode in _R18_MODE_MAP:
        # R18 path: requires Pixiv credentials, uses App API
        cache_key = f"pixiv:ranking:{mode}:{date}:{page}"
        cached = await cache.get_json(cache_key)
        if cached is not None:
            return cached

        locale = parse_accept_language(request.headers.get("Accept-Language", "en"))
        client = await _make_client(locale)
        offset = (page - 1) * 30
        async with client:
            try:
                result = await client.illust_ranking(
                    mode=_R18_MODE_MAP[mode],
                    date=date,
                    offset=offset,
                )
            except PermissionError:
                raise api_error(401, "pixiv_token_invalid", locale)
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"Pixiv ranking request failed: {e}")

        illusts = result.get("illusts", [])
        response = {
            "contents": [
                {
                    "illust_id": illust["id"],
                    "title": illust["title"],
                    "user_name": illust["user"]["name"],
                    "url": illust["image_urls"]["square_medium"],
                    "rank": offset + idx + 1,
                }
                for idx, illust in enumerate(illusts)
            ],
            "mode": mode,
            "content": "all",
            "date": date or "",
            "page": page,
            "prev_date": None,
            "next_date": None,
            "rank_total": 500,
            "has_next": result.get("next_offset") is not None,
        }
        await cache.set_json(cache_key, response, 300)
        return response

    # Public path: ranking.php (no credentials required)
    cache_key = f"pixiv:ranking:{mode}:{content}:{date}:{page}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return cached

    params: dict = {"format": "json", "mode": mode, "content": content, "p": page}
    if date:
        params["date"] = date

    headers = _ajax_headers()

    async with browser_client(timeout=30, follow_redirects=True) as http:
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

    result["has_next"] = len(result.get("contents", [])) >= 50
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

    headers = _ajax_headers()

    async with browser_client(timeout=30, follow_redirects=True) as http:
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
        illusts.append(
            {
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
            }
        )

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
        for item in popular_permanent + popular_recent:
            popular_illusts.append(
                {
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
                }
            )
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
