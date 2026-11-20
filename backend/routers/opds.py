"""OPDS Atom feed router for Jyzrox."""

import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from core.auth import gallery_access_filter, require_opds_auth
from core.config import settings as app_settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import Gallery, UserFavorite
from routers import opds_catalog
from services.opds_feed import (
    ATOM_NS,
)
from services.opds_feed import (
    base_url as _base_url,
)
from services.opds_feed import (
    build_acquisition_feed as _build_acquisition_feed,
)
from services.opds_feed import (
    make_feed as _make_feed,
)
from services.opds_feed import (
    now_iso as _now_iso,
)
from services.opds_feed import (
    xml_response as _xml_response,
)


async def _require_opds_enabled():
    """Raise 404 if OPDS feature is disabled."""
    val = await get_redis().get("setting:opds_enabled")
    if val is not None:
        enabled = val == b"1"
    else:
        enabled = app_settings.opds_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="OPDS is disabled")


router = APIRouter(tags=["opds"], dependencies=[Depends(_require_opds_enabled)])


# ── Root navigation feed ───────────────────────────────────────────────


@router.get("/")
async def opds_root(
    request: Request,
    _: dict = Depends(require_opds_auth),
):
    """OPDS root navigation feed."""
    base = _base_url(request)
    root = _make_feed("Jyzrox Library", "urn:jyzrox:opds:root", request)

    sections = [
        ("All Galleries", "urn:jyzrox:opds:all", f"{base}/opds/all", "Browse all galleries"),
        ("Recent", "urn:jyzrox:opds:recent", f"{base}/opds/recent", "Recently added galleries"),
        ("Favorites", "urn:jyzrox:opds:favorites", f"{base}/opds/favorites", "Favorited galleries"),
        ("Search", "urn:jyzrox:opds:search", f"{base}/opds/search", "Search galleries"),
    ]

    for title, feed_id, href, summary in sections:
        entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")

        title_el = ET.SubElement(entry, f"{{{ATOM_NS}}}title")
        title_el.text = title

        id_el = ET.SubElement(entry, f"{{{ATOM_NS}}}id")
        id_el.text = feed_id

        updated_el = ET.SubElement(entry, f"{{{ATOM_NS}}}updated")
        updated_el.text = _now_iso()

        link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
        link.set("rel", "subsection")
        link.set("href", href)
        link.set("type", "application/atom+xml;profile=opds-catalog;kind=acquisition")

        summary_el = ET.SubElement(entry, f"{{{ATOM_NS}}}summary")
        summary_el.text = summary

    return _xml_response(root)


# ── All galleries ──────────────────────────────────────────────────────


@router.get("/all")
async def opds_all(
    request: Request,
    page: int = 0,
    limit: int = 50,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS acquisition feed: all galleries, paginated."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Gallery)
                    .where(gallery_access_filter(auth))
                    .order_by(Gallery.added_at.desc())
                    .limit(limit + 1)
                    .offset(page * limit)
                )
            )
            .scalars()
            .all()
        )

    has_more = len(rows) > limit
    galleries = rows[:limit]

    return await _build_acquisition_feed(
        title="All Galleries",
        feed_id="urn:jyzrox:opds:all",
        request=request,
        galleries=galleries,
        page=page,
        limit=limit,
        has_more=has_more,
    )


# ── Recent ─────────────────────────────────────────────────────────────


@router.get("/recent")
async def opds_recent(
    request: Request,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS acquisition feed: last 50 galleries."""
    async with async_session() as session:
        galleries = (
            (
                await session.execute(
                    select(Gallery).where(gallery_access_filter(auth)).order_by(Gallery.added_at.desc()).limit(50)
                )
            )
            .scalars()
            .all()
        )

    return await _build_acquisition_feed(
        title="Recent Galleries",
        feed_id="urn:jyzrox:opds:recent",
        request=request,
        galleries=galleries,
        page=0,
        limit=50,
        has_more=False,
    )


# ── Favorites ──────────────────────────────────────────────────────────


@router.get("/favorites")
async def opds_favorites(
    request: Request,
    page: int = 0,
    limit: int = 50,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS acquisition feed: favorited galleries (per-user favorites)."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(Gallery)
                    .join(UserFavorite, Gallery.id == UserFavorite.gallery_id)
                    .where(
                        UserFavorite.user_id == auth["user_id"],
                        gallery_access_filter(auth),
                    )
                    .order_by(Gallery.added_at.desc())
                    .limit(limit + 1)
                    .offset(page * limit)
                )
            )
            .scalars()
            .all()
        )

    has_more = len(rows) > limit
    galleries = rows[:limit]

    return await _build_acquisition_feed(
        title="Favorite Galleries",
        feed_id="urn:jyzrox:opds:favorites",
        request=request,
        galleries=galleries,
        page=page,
        limit=limit,
        has_more=has_more,
    )


router.include_router(opds_catalog.router)
