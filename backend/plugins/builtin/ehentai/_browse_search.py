"""E-Hentai browse routes: status, search and image search."""

import logging

import httpx
from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import and_, select

from core.auth import gallery_access_filter, require_auth
from core.database import async_session
from core.errors import api_error
from db.models import Gallery, ReadProgress, UserFavorite
from plugins.builtin.ehentai._browse_common import (
    _browse_router,
    _filter_blocked,
    _get_blocked_tags,
    _locale,
    _make_client,
)
from services import cache
from services.cache import push_system_alert

logger = logging.getLogger(__name__)


@_browse_router.get("/browse-status")
async def get_browse_status(
    gids: str = Query(default="", max_length=4096),
    auth: dict = Depends(require_auth),
):
    """Batch local-library state for EH browse cards."""
    raw_ids = [part.strip() for part in gids.split(",") if part.strip()]
    if any(not part.isdigit() for part in raw_ids):
        raise HTTPException(status_code=422, detail="gids must be comma-separated numeric gallery IDs")
    unique_ids = list(dict.fromkeys(raw_ids))
    if len(unique_ids) > 300:
        raise HTTPException(status_code=422, detail="At most 300 gallery IDs may be requested")
    if not unique_ids:
        return {"statuses": {}}

    user_id = auth["user_id"]
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    Gallery.id,
                    Gallery.source_id,
                    Gallery.download_status,
                    ReadProgress.last_page,
                    UserFavorite.gallery_id.label("favorite_gallery_id"),
                )
                .outerjoin(
                    ReadProgress,
                    and_(ReadProgress.gallery_id == Gallery.id, ReadProgress.user_id == user_id),
                )
                .outerjoin(
                    UserFavorite,
                    and_(UserFavorite.gallery_id == Gallery.id, UserFavorite.user_id == user_id),
                )
                .where(
                    Gallery.source == "ehentai",
                    Gallery.source_id.in_(unique_ids),
                    gallery_access_filter(auth),
                )
            )
        ).all()

    return {
        "statuses": {
            row.source_id: {
                "gallery_id": row.id,
                "download_status": row.download_status,
                "downloaded": row.download_status in {"complete", "completed", "partial"},
                "last_page": row.last_page or 0,
                "is_local_favorite": row.favorite_gallery_id is not None,
            }
            for row in rows
        }
    }


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


@_browse_router.post("/image-search")
async def image_search(
    request: Request,
    image: UploadFile = File(...),
    similar: bool = Form(default=True),
    covers: bool = Form(default=False),
    expunged: bool = Form(default=False),
    auth: dict = Depends(require_auth),
):
    """Reverse-search EH with an unchanged JPEG upload."""
    content = await image.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be 10 MB or smaller")
    if not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=422, detail="EH image search requires a JPEG file")

    client = await _make_client()
    async with client:
        try:
            result = await client.image_search(
                content,
                image.filename or "search.jpg",
                similar=similar,
                covers=covers,
                expunged=expunged,
            )
        except PermissionError as e:
            detail = str(e)
            await push_system_alert(detail)
            if "509" in detail:
                raise api_error(403, "eh_bandwidth_exceeded", _locale(request))
            if "Sad Panda" in detail:
                raise api_error(403, "eh_access_denied", _locale(request))
            raise api_error(401, "eh_cookie_invalid", _locale(request))
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            logger.error("EH image search failed: %s", e)
            raise HTTPException(status_code=502, detail=str(e))

    blocked = await _get_blocked_tags(auth["user_id"])
    if blocked and result.get("galleries"):
        result["galleries"] = _filter_blocked(result["galleries"], blocked)
    return result


# ── Popular ──────────────────────────────────────────────────────────
