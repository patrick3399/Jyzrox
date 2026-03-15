"""RSS/Atom feed router for Jyzrox — authenticated via API token query parameter."""

import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import desc, select, text

from core.auth import gallery_access_filter
from core.database import async_session
from db.models import DownloadJob, Gallery, Subscription

logger = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM_NS)

router = APIRouter(tags=["rss"])


async def _verify_rss_token(token: str = Query(..., alias="token")) -> dict:
    """Verify API token passed as ?token= query parameter."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token parameter")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            text(
                "SELECT t.id, t.user_id, u.role "
                "FROM api_tokens t JOIN users u ON t.user_id = u.id "
                "WHERE t.token_hash = :hash AND (t.expires_at IS NULL OR t.expires_at > now())"
            ),
            {"hash": token_hash},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"user_id": row.user_id, "token_id": row.id, "role": row.role or "viewer"}


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost")
    return f"{proto}://{host}"


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

    base = _base_url(request)
    path = request.url.path
    self_link = ET.SubElement(root, f"{{{ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("href", f"{base}{path}")
    self_link.set("type", "application/atom+xml")

    return root


def _gallery_atom_entry(gallery: Gallery, base_url: str) -> ET.Element:
    """Build an Atom <entry> element for a gallery."""
    entry = ET.Element(f"{{{ATOM_NS}}}entry")

    title_el = ET.SubElement(entry, f"{{{ATOM_NS}}}title")
    title_el.text = gallery.title or gallery.title_jpn or f"Gallery {gallery.id}"

    id_el = ET.SubElement(entry, f"{{{ATOM_NS}}}id")
    id_el.text = f"urn:jyzrox:gallery:{gallery.source}:{gallery.source_id}"

    updated_el = ET.SubElement(entry, f"{{{ATOM_NS}}}updated")
    updated_el.text = (gallery.added_at or datetime.now(UTC)).isoformat()

    link_el = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
    link_el.set("href", f"{base_url}/library/{gallery.source}/{gallery.source_id}")
    link_el.set("rel", "alternate")

    if gallery.tags_array:
        for tag in gallery.tags_array[:20]:  # limit to avoid bloat
            cat = ET.SubElement(entry, f"{{{ATOM_NS}}}category")
            cat.set("term", tag)

    summary_parts = []
    if gallery.pages:
        summary_parts.append(f"{gallery.pages} pages")
    if gallery.category:
        summary_parts.append(gallery.category)
    if gallery.uploader:
        summary_parts.append(f"by {gallery.uploader}")
    if summary_parts:
        summary_el = ET.SubElement(entry, f"{{{ATOM_NS}}}summary")
        summary_el.text = " — ".join(summary_parts)

    return entry


def _xml_response(root: ET.Element) -> Response:
    xml_str = ET.tostring(root, xml_declaration=True, encoding="unicode")
    return Response(content=xml_str, media_type="application/atom+xml; charset=utf-8")


# ── Recent galleries feed ──────────────────────────────────────────────


@router.get("/recent")
async def rss_recent(
    request: Request,
    auth: dict = Depends(_verify_rss_token),
):
    """Atom feed of the 50 most recently added galleries."""
    async with async_session() as session:
        galleries = (
            await session.execute(
                select(Gallery)
                .where(gallery_access_filter(auth))
                .order_by(desc(Gallery.added_at))
                .limit(50)
            )
        ).scalars().all()

    base_url = _base_url(request)
    root = _make_feed("Recent Galleries — Jyzrox", "urn:jyzrox:rss:recent", request)

    for gallery in galleries:
        entry = _gallery_atom_entry(gallery, base_url)
        root.append(entry)

    return _xml_response(root)


# ── Subscription feed ──────────────────────────────────────────────────


@router.get("/subscriptions/{sub_id}")
async def rss_subscription(
    sub_id: int,
    request: Request,
    auth: dict = Depends(_verify_rss_token),
):
    """Atom feed of completed downloads for a specific subscription."""
    async with async_session() as session:
        subscription = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id)
            )
        ).scalar_one_or_none()

    if not subscription or subscription.user_id != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Subscription not found")

    async with async_session() as session:
        # Join download_jobs to galleries for done jobs belonging to this subscription
        rows = (
            await session.execute(
                select(Gallery)
                .join(DownloadJob, DownloadJob.gallery_id == Gallery.id)
                .where(
                    DownloadJob.subscription_id == sub_id,
                    DownloadJob.status == "done",
                    DownloadJob.gallery_id.isnot(None),
                    gallery_access_filter(auth),
                )
                .order_by(desc(DownloadJob.finished_at))
                .limit(50)
            )
        ).scalars().all()

    sub_name = subscription.name or f"Subscription {sub_id}"
    base_url = _base_url(request)
    root = _make_feed(
        f"{sub_name} — Jyzrox",
        f"urn:jyzrox:rss:subscription:{sub_id}",
        request,
    )

    for gallery in rows:
        entry = _gallery_atom_entry(gallery, base_url)
        root.append(entry)

    return _xml_response(root)
