"""Shared OPDS feed builders."""

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import func, select

from core.database import async_session
from core.gallery_helpers import build_cover_sha_map
from db.models import Gallery, Image
from services.cas import thumb_url as cas_thumb_url

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


def base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost")
    return f"{proto}://{host}"


def xml_response(root: ET.Element) -> Response:
    xml_str = ET.tostring(root, xml_declaration=True, encoding="unicode")
    return Response(content=xml_str, media_type="application/atom+xml; charset=utf-8")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_feed(title: str, feed_id: str, request: Request) -> ET.Element:
    root = ET.Element(f"{{{ATOM_NS}}}feed")

    title_el = ET.SubElement(root, f"{{{ATOM_NS}}}title")
    title_el.text = title

    id_el = ET.SubElement(root, f"{{{ATOM_NS}}}id")
    id_el.text = feed_id

    updated_el = ET.SubElement(root, f"{{{ATOM_NS}}}updated")
    updated_el.text = now_iso()

    author = ET.SubElement(root, f"{{{ATOM_NS}}}author")
    name_el = ET.SubElement(author, f"{{{ATOM_NS}}}name")
    name_el.text = "Jyzrox"

    # Self link
    base = base_url(request)
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


def gallery_entry(gallery: Gallery, cover_thumb: str | None, request: Request, pending_pages: int = 0) -> ET.Element:
    base = base_url(request)
    entry = ET.Element(f"{{{ATOM_NS}}}entry")

    # PSE count must match the page list served by opds_gallery(), which only
    # contains hashed pages; gallery.pages also counts pending link pages.
    entry.set(f"{{{PSE_NS}}}count", str(max((gallery.pages or 0) - pending_pages, 0)))

    title = gallery.title or gallery.title_jpn or f"Gallery {gallery.id}"
    title_el = ET.SubElement(entry, f"{{{ATOM_NS}}}title")
    title_el.text = title

    id_el = ET.SubElement(entry, f"{{{ATOM_NS}}}id")
    id_el.text = f"urn:jyzrox:gallery:{gallery.source}:{gallery.source_id}"

    updated_el = ET.SubElement(entry, f"{{{ATOM_NS}}}updated")
    if gallery.added_at:
        updated_el.text = gallery.added_at.isoformat()
    else:
        updated_el.text = now_iso()

    author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
    name_el = ET.SubElement(author, f"{{{ATOM_NS}}}name")
    name_el.text = gallery.uploader or "Unknown"

    # Subsection link to gallery page list
    sub_link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
    sub_link.set("rel", "subsection")
    sub_link.set("href", f"{base}/opds/gallery/{gallery.source}/{gallery.source_id}")
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


# ── Shared acquisition feed builder ───────────────────────────────────


async def build_acquisition_feed(
    title: str,
    feed_id: str,
    request: Request,
    galleries: list,
    page: int,
    limit: int,
    has_more: bool,
    next_href: str | None = None,
) -> Response:
    base = base_url(request)
    root = make_feed(title, feed_id, request)

    # Collect cover thumbs in batch: first image per gallery (page_num=1)
    gallery_ids = [g.id for g in galleries]
    cover_thumbs: dict[int, str] = {}
    pending_counts: dict[int, int] = {}

    if gallery_ids:
        source_map = {g.id: g.source or "" for g in galleries}

        async with async_session() as session:
            cover_thumbs = {
                gallery_id: cas_thumb_url(sha256)
                for gallery_id, sha256 in (await build_cover_sha_map(session, gallery_ids, source_map)).items()
            }
            pending_counts = {
                gallery_id: count
                for gallery_id, count in (
                    await session.execute(
                        select(Image.gallery_id, func.count(Image.id))
                        .where(
                            Image.gallery_id.in_(gallery_ids),
                            Image.visibility == "active",
                            Image.blob_sha256.is_(None),
                            Image.external_path.is_not(None),
                        )
                        .group_by(Image.gallery_id)
                    )
                ).all()
            }

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
        entry = gallery_entry(gallery, cover_thumbs.get(gallery.id), request, pending_counts.get(gallery.id, 0))
        root.append(entry)

    return xml_response(root)
