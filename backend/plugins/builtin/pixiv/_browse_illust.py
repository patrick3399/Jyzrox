"""Pixiv browse routes: illust detail, pages and user profile."""

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core.auth import require_auth
from core.errors import api_error
from plugins.builtin.pixiv._browse_common import _ajax_headers, _browse_router, _locale, _make_client
from services import cache
from services.browser_http import browser_client
from services.credential import get_credential
from services.pixiv_client import PixivClient

# ── Illust detail ─────────────────────────────────────────────────────


async def _fetch_illust_public(illust_id: int) -> dict:
    """Fetch illust detail via Pixiv public ajax API (no credentials required)."""
    headers = _ajax_headers()

    async with browser_client(timeout=30, follow_redirects=True) as http:
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
        async with browser_client(timeout=30, follow_redirects=True) as http:
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
        meta_pages.append(
            {
                "image_urls": {
                    "square_medium": p_urls.get("thumb_mini", ""),
                    "medium": p_urls.get("small", ""),
                    "large": p_urls.get("regular", ""),
                    "original": p_urls.get("original", ""),
                }
            }
        )

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
        "meta_single_page": ({"original_image_url": urls.get("original", "")} if body.get("pageCount", 1) == 1 else {}),
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


@_browse_router.get("/illust/{illust_id}/pages")
async def get_illust_pages(
    illust_id: int,
    _: dict = Depends(require_auth),
):
    """Get all page original URLs for a multi-page illust (cached 1h)."""
    # Try to reuse existing illust cache first
    cached = await cache.get_pixiv_illust_cache(illust_id)

    meta_pages = None
    page_count = 1
    image_urls: dict = {}
    if cached is not None:
        meta_pages = cached.get("meta_pages")
        page_count = cached.get("page_count", 1)
        image_urls = cached.get("image_urls") or {}

    # If no meta_pages in cache, try auth client first (avoids race with /illust/{id})
    if meta_pages is None:
        refresh_token = await get_credential("pixiv")
        if refresh_token:
            client = PixivClient(refresh_token=refresh_token)
            async with client:
                try:
                    result = await client.illust_detail(illust_id)
                    await cache.set_pixiv_illust_cache(illust_id, result)
                    meta_pages = result.get("meta_pages") or []
                    page_count = result.get("page_count", 1)
                    image_urls = result.get("image_urls") or {}
                except PermissionError, ValueError, httpx.HTTPError:
                    pass

    # Final fallback to public API (no credentials / auth failed)
    if meta_pages is None:
        public_data = await _fetch_illust_public(illust_id)
        meta_pages = public_data.get("meta_pages") or []
        page_count = public_data.get("page_count", 1)
        image_urls = public_data.get("image_urls") or {}

    if meta_pages:
        pages = [
            {
                "page_num": i + 1,
                "url": mp["image_urls"].get("original") or mp["image_urls"].get("large", ""),
            }
            for i, mp in enumerate(meta_pages)
        ]
    else:
        # Single-page illust
        url = image_urls.get("original") or image_urls.get("large", "")
        pages = [{"page_num": 1, "url": url}]
        page_count = 1

    return {"pages": pages, "page_count": page_count}


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
