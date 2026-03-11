"""Generic gallery-dl metadata parsing for the Parseable protocol."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from plugins.models import GalleryImportData

logger = logging.getLogger(__name__)

_BOORU_SOURCES = frozenset({
    "danbooru", "gelbooru", "e621", "yandere", "konachan",
    "rule34", "safebooru", "sankaku",
})

NAMESPACE_MAP = {
    "copyright": "parody",
    "meta": "meta",
    "general": "general",
    "artist": "artist",
    "character": "character",
    "species": "species",
}


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

    # Source detection
    source = meta.get("category") or "gallery_dl"

    # Source ID extraction
    source_id = str(
        meta.get("gallery_id")
        or meta.get("tweet_id")
        or meta.get("id")
        or dest_dir.name
    )

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
        title=(
            meta.get("title")
            or meta.get("title_en")
            or (meta.get("description") or "")[:120]
            or (meta.get("content") or "")[:120]
            or f"{source}_{source_id}"
        ),
        title_jpn=meta.get("title_jpn") or meta.get("title_original") or "",
        category=meta.get("category") or meta.get("type", ""),
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
    if source not in _BOORU_SOURCES:
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
    """Extract artist_id from metadata based on source type."""
    # Twitter-specific
    if meta.get("category") == "twitter" or source == "twitter":
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

    # Booru sources — artist from tags
    if source in _BOORU_SOURCES or source in ("nhentai", "hitomi"):
        for tag in tags:
            if tag.startswith("artist:"):
                return f"{source}:{tag[7:]}"

    # Generic fallback — use uploader
    uploader = meta.get("uploader", "")
    if uploader:
        return f"{source}:{uploader}"

    return None
