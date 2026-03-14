"""Generic gallery-dl metadata parsing for the Parseable protocol."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from plugins.models import GalleryImportData

logger = logging.getLogger(__name__)

NAMESPACE_MAP = {
    "copyright": "parody",
    "meta": "meta",
    "general": "general",
    "artist": "artist",
    "character": "character",
    "species": "species",
}


def _extract_title(source: str, meta: dict, source_id: str) -> str:
    """Extract title from metadata using per-source field priority."""
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    fields = cfg.title_fields

    for field_name in fields:
        val = meta.get(field_name)
        if val:
            return str(val)[:200]

    # Fallback chain
    return (
        (meta.get("title") or "")[:200]
        or (meta.get("title_en") or "")[:200]
        or (meta.get("description") or "")[:120]
        or (meta.get("content") or "")[:120]
        or f"{source}_{source_id}"
    )


def parse_gallery_dl_import(dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
    """Parse a gallery-dl download directory into GalleryImportData."""
    meta = raw_meta or {}
    if not meta:
        for meta_file in sorted(dest_dir.rglob("*.json")):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                break
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                logger.warning("[gallery_dl_metadata] failed to read %s: %s", meta_file, exc)
                continue

    # Source detection: gallery-dl uses "category" for the extractor name
    # (e.g., "exhentai", "pixiv"). Resolve through site config to get the
    # canonical source_id (e.g., "ehentai").
    raw_source = meta.get("category") or "gallery_dl"
    from plugins.builtin.gallery_dl._sites import get_site_config as _get_site_config
    _cfg = _get_site_config(raw_source)
    source = _cfg.source_id
    source_id = dest_dir.name
    for _field in _cfg.source_id_fields:
        _val = meta.get(_field)
        if _val:
            source_id = str(_val)
            break

    # Tag extraction and normalization
    tags = _extract_tags(dest_dir, meta)
    tags = _normalize_tags(tags, source)

    # Artist extraction
    artist_id = _extract_artist(source, meta, tags)

    # Date parsing
    posted_at: datetime | None = None
    raw_date = meta.get("date") or meta.get("posted")
    if raw_date:
        try:
            if isinstance(raw_date, (int, float)):
                posted_at = datetime.fromtimestamp(raw_date, tz=UTC)
            else:
                posted_at = datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError, OverflowError):
            pass

    return GalleryImportData(
        source=source,
        source_id=source_id,
        title=_extract_title(source, meta, source_id),
        title_jpn=meta.get("title_jpn") or meta.get("title_original") or "",
        category=meta.get("gallery_category") or meta.get("subcategory") or meta.get("type", ""),
        language=meta.get("lang") or meta.get("language", ""),
        tags=tags,
        artist_id=artist_id,
        posted_at=posted_at,
        uploader=meta.get("uploader", ""),
        extra={},
    )


def _extract_tags(gallery_path: Path, metadata: dict) -> list[str]:
    """Extract tags in 'namespace:name' format from metadata or tags.txt."""
    tags: list[str] = []

    raw = metadata.get("tags")
    if isinstance(raw, dict):
        for ns, names in raw.items():
            tags.extend(f"{ns}:{n}" for n in names)
    elif isinstance(raw, list):
        tags.extend(raw)

    # Add rating as tag if present
    rating = metadata.get("rating")
    if rating:
        tags.append(f"rating:{rating}")

    if not tags:
        tags_file = gallery_path / "tags.txt"
        if tags_file.exists():
            try:
                tags = [t.strip() for t in tags_file.read_text().splitlines() if t.strip()]
            except OSError:
                pass

    return tags


def _normalize_tags(tags: list[str], source: str) -> list[str]:
    """Normalize namespace names across booru sources for consistency."""
    from plugins.builtin.gallery_dl._sites import get_site_config
    cfg = get_site_config(source)
    if not cfg.normalize_namespaces:
        return tags
    normalized = []
    for tag in tags:
        if ":" in tag:
            ns, name = tag.split(":", 1)
            ns = NAMESPACE_MAP.get(ns, ns)
            normalized.append(f"{ns}:{name}")
        else:
            normalized.append(tag)
    return normalized


def _extract_artist(source: str, meta: dict, tags: list[str]) -> str | None:
    """Extract artist_id from metadata based on source type (data-driven)."""
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    strategy = cfg.artist_from

    if strategy == "twitter_author":
        handle = None
        author = meta.get("author")
        if isinstance(author, dict):
            handle = author.get("name")
        if not handle:
            user = meta.get("user")
            handle = user if isinstance(user, str) else None
        if not handle:
            handle = meta.get("uploader")
        if handle:
            return f"twitter:{handle}"
    elif strategy == "tag":
        for tag in tags:
            if tag.startswith("artist:"):
                return f"{source}:{tag[7:]}"
    elif strategy == "uploader":
        uploader = meta.get("uploader", "")
        if uploader:
            return f"{source}:{uploader}"
    # strategy == "none" or no match
    return None
