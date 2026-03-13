"""OPDS Atom feed router for Jyzrox."""

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_opds_auth
from core.config import settings as app_settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import Gallery, Image, UserFavorite
from services.cas import cas_url, thumb_url as cas_thumb_url


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

# XML namespaces
ATOM_NS = "http://www.w3.org/2005/Atom"
OPDS_NS = "http://opds-spec.org/2010/catalog"
PSE_NS = "http://vaemendis.net/opds-pse/ns"
DC_NS = "http://purl.org/dc/terms/"
OS_NS = "http://a9.com/-/spec/opensearch/1.1/"

# Register namespaces globally to avoid ns0/ns1 prefixes
ET.register_namespace("", ATOM_NS)
ET.register_namespace("opds", OPDS_NS)
ET.register_namespace("pse", PSE_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("opensearch", OS_NS)


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost")
    return f"{proto}://{host}"


def _xml_response(root: ET.Element) -> Response:
    xml_str = ET.tostring(root, xml_declaration=True, encoding="unicode")
    return Response(content=xml_str, media_type="application/atom+xml; charset=utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_feed(title: str, feed_id: str, request: Request) -> ET.Element:
    root = ET.Element(f"{{{ATOM_NS}}}feed")

    title_el = ET.SubElement(root, f"{{{ATOM_NS}}}title")
    title_el.text = title

    id_el = ET.SubElement(root, f"{{{ATOM_NS}}}id")
    id_el.text = feed_id

    updated_el = ET.SubElement(root, f"{{{ATOM_NS}}}updated")
    updated_el.text = _now_iso()

    author = ET.SubElement(root, f"{{{ATOM_NS}}}author")
    name_el = ET.SubElement(author, f"{{{ATOM_NS}}}name")
    name_el.text = "Jyzrox"

    # Self link
    base = _base_url(request)
    path = request.url.path
    self_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("href", f"{base}{path}")
    self_link.set("type", "application/atom+xml;profile=opds-catalog")

    # Start link pointing to root catalog
    start_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
    start_link.set("rel", "start")
    start_link.set("href", f"{base}/opds/")
    start_link.set("type", "application/atom+xml;profile=opds-catalog;kind=navigation")

    # OpenSearch link
    search_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
    search_link.set("rel", "search")
    search_link.set("href", f"{base}/opds/opensearch.xml")
    search_link.set("type", "application/opensearchdescription+xml")

    return root


def _gallery_entry(gallery: Gallery, cover_thumb: str | None, request: Request) -> ET.Element:
    base = _base_url(request)
    entry = ET.Element(f"{{{ATOM_NS}}}entry")

    # PSE count (total pages)
    entry.set(f"{{{PSE_NS}}}count", str(gallery.pages or 0))

    title = gallery.title or gallery.title_jpn or f"Gallery {gallery.id}"
    title_el = ET.SubElement(entry, f"{{{ATOM_NS}}}title")
    title_el.text = title

    id_el = ET.SubElement(entry, f"{{{ATOM_NS}}}id")
    id_el.text = f"urn:jyzrox:gallery:{gallery.id}"

    updated_el = ET.SubElement(entry, f"{{{ATOM_NS}}}updated")
    if gallery.added_at:
        updated_el.text = gallery.added_at.isoformat()
    else:
        updated_el.text = _now_iso()

    author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
    name_el = ET.SubElement(author, f"{{{ATOM_NS}}}name")
    name_el.text = gallery.uploader or "Unknown"

    # Subsection link to gallery page list
    sub_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
    sub_link.set("rel", "subsection")
    sub_link.set("href", f"{base}/opds/gallery/{gallery.id}")
    sub_link.set("type", "application/atom+xml;profile=opds-catalog;kind=acquisition")

    # Cover thumbnail link
    if cover_thumb:
        thumb_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
        thumb_link.set("rel", "http://opds-spec.org/image/thumbnail")
        thumb_link.set("href", f"{base}{cover_thumb}")
        thumb_link.set("type", "image/webp")

    # Tags as categories
    if gallery.tags_array:
        for tag in gallery.tags_array:
            cat = ET.SubElement(entry, f"{{{ATOM_NS}}}category")
            cat.set("term", tag)
            cat.set("label", tag)

    # dc:language
    if gallery.language:
        lang_el = ET.SubElement(entry, f"{{{DC_NS}}}language")
        lang_el.text = gallery.language

    # Summary
    summary_parts = []
    if gallery.pages:
        summary_parts.append(f"{gallery.pages} pages")
    if gallery.category:
        summary_parts.append(gallery.category)
    if summary_parts:
        summary_el = ET.SubElement(entry, f"{{{ATOM_NS}}}summary")
        summary_el.text = " — ".join(summary_parts)

    return entry


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


# ── Shared acquisition feed builder ───────────────────────────────────


async def _build_acquisition_feed(
    title: str,
    feed_id: str,
    request: Request,
    galleries: list,
    page: int,
    limit: int,
    has_more: bool,
    next_href: str | None = None,
) -> Response:
    base = _base_url(request)
    root = _make_feed(title, feed_id, request)

    # Collect cover thumbs in batch: first image per gallery (page_num=1)
    gallery_ids = [g.id for g in galleries]
    cover_thumbs: dict[int, str] = {}

    if gallery_ids:
        async with async_session() as session:
            max_page_sub = (
                select(Image.gallery_id, func.max(Image.page_num).label("max_page"))
                .where(Image.gallery_id.in_(gallery_ids))
                .group_by(Image.gallery_id)
            ).subquery()
            cover_rows = (
                await session.execute(
                    select(Image)
                    .join(max_page_sub, and_(Image.gallery_id == max_page_sub.c.gallery_id, Image.page_num == max_page_sub.c.max_page))
                    .options(selectinload(Image.blob))
                )
            ).scalars().all()

        for img in cover_rows:
            if img.blob and img.blob.sha256:
                cover_thumbs[img.gallery_id] = cas_thumb_url(img.blob.sha256)

    # Pagination links
    if page > 0:
        prev_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
        prev_link.set("rel", "previous")
        prev_page = page - 1
        base_path = request.url.path
        prev_link.set("href", f"{base}{base_path}?page={prev_page}&limit={limit}")
        prev_link.set("type", "application/atom+xml;profile=opds-catalog;kind=acquisition")

    if has_more:
        next_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
        next_link.set("rel", "next")
        next_page = page + 1
        base_path = request.url.path
        next_link.set("href", f"{base}{base_path}?page={next_page}&limit={limit}")
        next_link.set("type", "application/atom+xml;profile=opds-catalog;kind=acquisition")

    for gallery in galleries:
        entry = _gallery_entry(gallery, cover_thumbs.get(gallery.id), request)
        root.append(entry)

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
            await session.execute(
                select(Gallery)
                .where(gallery_access_filter(auth))
                .order_by(Gallery.added_at.desc())
                .limit(limit + 1)
                .offset(page * limit)
            )
        ).scalars().all()

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
            await session.execute(
                select(Gallery)
                .where(gallery_access_filter(auth))
                .order_by(Gallery.added_at.desc())
                .limit(50)
            )
        ).scalars().all()

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
        ).scalars().all()

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


# ── Search ─────────────────────────────────────────────────────────────


@router.get("/search")
async def opds_search(
    request: Request,
    q: str = "",
    page: int = 0,
    limit: int = 50,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS acquisition feed: search galleries by title."""
    query = select(Gallery).where(gallery_access_filter(auth)).order_by(Gallery.added_at.desc())
    if q:
        query = query.where(Gallery.title.ilike(f"%{q}%"))

    async with async_session() as session:
        rows = (
            await session.execute(
                query.limit(limit + 1).offset(page * limit)
            )
        ).scalars().all()

    has_more = len(rows) > limit
    galleries = rows[:limit]

    return await _build_acquisition_feed(
        title=f"Search: {q}" if q else "All Galleries",
        feed_id="urn:jyzrox:opds:search",
        request=request,
        galleries=galleries,
        page=page,
        limit=limit,
        has_more=has_more,
    )


# ── OpenSearch descriptor ──────────────────────────────────────────────


@router.get("/opensearch.xml")
async def opds_opensearch(
    request: Request,
    _: dict = Depends(require_opds_auth),
):
    """OpenSearch descriptor for OPDS search."""
    base = _base_url(request)
    xml_str = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
        "<ShortName>Jyzrox</ShortName>"
        "<Description>Search the Jyzrox library</Description>"
        f'<Url type="application/atom+xml;profile=opds-catalog" template="{base}/opds/search?q={{searchTerms}}"/>'
        "</OpenSearchDescription>"
    )
    return Response(content=xml_str, media_type="application/opensearchdescription+xml")


# ── Single gallery page list (OPDS-PSE) ───────────────────────────────


@router.get("/gallery/{gallery_id}")
async def opds_gallery(
    gallery_id: int,
    request: Request,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS-PSE page list for a single gallery."""
    async with async_session() as session:
        gallery = (
            await session.execute(
                select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth))
            )
        ).scalar_one_or_none()

        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        images = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .order_by(Image.page_num.desc())
                .options(selectinload(Image.blob))
            )
        ).scalars().all()

    base = _base_url(request)
    title = gallery.title or gallery.title_jpn or f"Gallery {gallery_id}"
    root = _make_feed(title, f"urn:jyzrox:gallery:{gallery_id}", request)

    for img in images:
        blob = img.blob
        entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")

        # PSE page index (0-based)
        entry.set(f"{{{PSE_NS}}}index", str(img.page_num - 1))

        title_el = ET.SubElement(entry, f"{{{ATOM_NS}}}title")
        title_el.text = f"Page {img.page_num}"

        id_el = ET.SubElement(entry, f"{{{ATOM_NS}}}id")
        id_el.text = f"urn:jyzrox:image:{img.id}"

        updated_el = ET.SubElement(entry, f"{{{ATOM_NS}}}updated")
        updated_el.text = _now_iso()

        if blob:
            # Full image link
            img_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
            img_link.set("rel", "http://opds-spec.org/image")
            img_link.set("href", f"{base}{cas_url(blob.sha256, blob.extension)}")

            # Determine image content type
            ext_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".avif": "image/avif",
            }
            content_type = ext_map.get(blob.extension.lower(), "image/jpeg")
            img_link.set("type", content_type)

            # Thumbnail link
            thumb_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
            thumb_link.set("rel", "http://opds-spec.org/image/thumbnail")
            thumb_link.set("href", f"{base}{cas_thumb_url(blob.sha256)}")
            thumb_link.set("type", "image/webp")

    return _xml_response(root)
