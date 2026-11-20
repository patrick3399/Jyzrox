"""Pixiv browse routes: user works, bookmarks and follow actions."""

import httpx
from fastapi import Depends, HTTPException, Query, Request

from core.auth import require_auth
from core.errors import api_error
from plugins.builtin.pixiv._browse_common import _browse_router, _locale, _make_client
from services import cache

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


# ── Illust bookmark operations ────────────────────────────────────────


@_browse_router.get("/illust/{illust_id}/bookmark")
async def get_illust_bookmark(
    illust_id: int,
    _: dict = Depends(require_auth),
):
    """Get bookmark status for an illust."""
    # Check cached illust data first (has is_bookmarked)
    cached = await cache.get_pixiv_illust_cache(illust_id)
    if cached is not None:
        return {"is_bookmarked": bool(cached.get("is_bookmarked", False))}

    # Fall back to Pixiv API
    try:
        client = await _make_client()
    except HTTPException:
        raise
    async with client:
        try:
            return await client.illust_bookmark_detail(illust_id)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))


@_browse_router.post("/illust/{illust_id}/bookmark")
async def add_illust_bookmark(
    illust_id: int,
    restrict: str = Query(default="public"),
    _: dict = Depends(require_auth),
):
    """Add bookmark for an illust."""
    client = await _make_client()
    async with client:
        try:
            await client.illust_bookmark_add(illust_id, restrict=restrict)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # Invalidate illust cache + all my_bookmarks pages
    from core.redis_client import get_redis

    await get_redis().delete(f"pixiv:illust:{illust_id}")
    await cache.invalidate_pixiv_search_cache("my_bookmarks")
    return {"ok": True}


@_browse_router.delete("/illust/{illust_id}/bookmark")
async def delete_illust_bookmark(
    illust_id: int,
    _: dict = Depends(require_auth),
):
    """Delete bookmark for an illust."""
    client = await _make_client()
    async with client:
        try:
            await client.illust_bookmark_delete(illust_id)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # Invalidate illust cache + all my_bookmarks pages
    from core.redis_client import get_redis

    await get_redis().delete(f"pixiv:illust:{illust_id}")
    await cache.invalidate_pixiv_search_cache("my_bookmarks")
    return {"ok": True}


# ── User follow operations ────────────────────────────────────────────


@_browse_router.post("/user/{user_id}/follow")
async def follow_user(
    user_id: int,
    restrict: str = Query(default="public"),
    _: dict = Depends(require_auth),
):
    """Follow a Pixiv user."""
    client = await _make_client()
    async with client:
        try:
            await client.user_follow_add(user_id, restrict=restrict)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # Invalidate user cache so is_followed refreshes + all following list/feed pages
    from core.redis_client import get_redis

    await get_redis().delete(f"pixiv:user:{user_id}")
    await cache.invalidate_pixiv_search_cache("my_following", "following_feed")
    return {"ok": True}


@_browse_router.delete("/user/{user_id}/follow")
async def unfollow_user(
    user_id: int,
    _: dict = Depends(require_auth),
):
    """Unfollow a Pixiv user."""
    client = await _make_client()
    async with client:
        try:
            await client.user_follow_delete(user_id)
        except PermissionError:
            raise api_error(401, "pixiv_token_invalid")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # Invalidate user cache so is_followed refreshes + all following list/feed pages
    from core.redis_client import get_redis

    await get_redis().delete(f"pixiv:user:{user_id}")
    await cache.invalidate_pixiv_search_cache("my_following", "following_feed")
    return {"ok": True}
