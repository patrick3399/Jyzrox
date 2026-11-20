"""OPDS search, OpenSearch, and gallery feeds."""

import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_opds_auth
from core.database import async_session
from core.gallery_helpers import image_not_excluded_clause
from core.source_display import get_display_config
from db.models import Gallery, Image
from services.cas import image_file_url
from services.cas import thumb_url as cas_thumb_url
from services.opds_feed import (
    ATOM_NS,
    PSE_NS,
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

router = APIRouter()


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
        rows = (await session.execute(query.limit(limit + 1).offset(page * limit))).scalars().all()

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


@router.get("/gallery/{source}/{source_id}")
async def opds_gallery(
    source: str,
    source_id: str,
    request: Request,
    auth: dict = Depends(require_opds_auth),
):
    """OPDS-PSE page list for a single gallery."""
    async with async_session() as session:
        gallery = (
            await session.execute(
                select(Gallery).where(
                    Gallery.source == source,
                    Gallery.source_id == source_id,
                    gallery_access_filter(auth),
                )
            )
        ).scalar_one_or_none()

        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        images = (
            (
                await session.execute(
                    select(Image)
                    .where(
                        Image.gallery_id == gallery.id,
                        Image.visibility == "active",
                        # Pending link pages have no blob to serve or thumbnail yet.
                        Image.blob_sha256.is_not(None),
                        image_not_excluded_clause(),
                    )
                    .order_by(
                        Image.page_num.desc()
                        if get_display_config(gallery.source or "").image_order == "desc"
                        else Image.page_num.asc()
                    )
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

    base = _base_url(request)
    title = gallery.title or gallery.title_jpn or f"Gallery {source}/{source_id}"
    root = _make_feed(title, f"urn:jyzrox:gallery:{source}:{source_id}", request)

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
            # A link page's bytes stay in the user's folder; it has no CAS file.
            img_link.set("href", f"{base}{image_file_url(blob, img.external_path)}")

            # Determine image content type
            ext_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".avif": "image/avif",
                ".jxl": "image/jxl",
            }
            content_type = ext_map.get(blob.extension.lower(), "image/jpeg")
            img_link.set("type", content_type)

            # Thumbnail link
            thumb_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
            thumb_link.set("rel", "http://opds-spec.org/image/thumbnail")
            thumb_link.set("href", f"{base}{cas_thumb_url(blob.sha256)}")
            thumb_link.set("type", "image/webp")

    return _xml_response(root)
