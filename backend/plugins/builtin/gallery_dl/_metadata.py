"""Generic gallery-dl metadata parsing for the Parseable protocol."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
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


_DIR_FMT_FIELD_RE = re.compile(r"\{(\w+)(?:\[(\w+)\])?\}")


@lru_cache(maxsize=64)
def _get_identity_field(category: str) -> tuple[str, str | None] | None:
    """Extract the identity field from gallery-dl's directory_fmt for a category.

    Returns (field, subfield) or None if no extractor found.
    E.g. kemono → ("user", None), twitter → ("user", "name")
    """
    try:
        from gallery_dl import extractor
        classes = [e for e in extractor._list_classes() if getattr(e, "category", None) == category]
        if not classes:
            return None
        fmt = classes[0].directory_fmt
        if not fmt or len(fmt) < 2:
            return None  # flat structure — no meaningful identity
        last = fmt[-1]
        m = _DIR_FMT_FIELD_RE.search(last)
        if m:
            return (m.group(1), m.group(2))  # (field, subfield_or_None)
    except (ImportError, AttributeError, IndexError, TypeError):
        pass
    return None


def _resolve_source_id(meta: dict, cfg, dest_dir_name: str) -> str:
    """Resolve source_id from metadata, using gallery-dl directory_fmt when available."""
    category = meta.get("category", "")

    # Try gallery-dl's directory_fmt first
    identity = _get_identity_field(category)
    if identity is not None:
        field, subfield = identity
        val = meta.get(field)
        if val is not None:
            if subfield and isinstance(val, dict):
                val = val.get(subfield)
            if val is not None and isinstance(val, (str, int)):
                return str(val)

    # Fallback: existing source_id_fields logic
    for f in cfg.source_id_fields:
        val = meta.get(f)
        if val:
            return str(val)

    return dest_dir_name


def _extract_title(source: str, meta: dict, source_id: str) -> str:
    """Extract title from metadata using per-source field priority."""
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    fields = cfg.title_fields

    for field_name in fields:
        # Support dot notation for nested fields (e.g., "author.name")
        val: object = meta
        for part in field_name.split("."):
            if isinstance(val, dict):
                val = val.get(part)
            else:
                val = None
                break
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


def parse_gallery_dl_import(dest_dir: Path, raw_meta: dict | None = None, *, fallback_source: str | None = None) -> GalleryImportData:
    """Parse a gallery-dl download directory into GalleryImportData.

    Args:
        fallback_source: canonical source_id to use when metadata has no
            "category" field (e.g., native plugin downloads without gallery-dl
            metadata).
    """
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
    raw_source = meta.get("category") or fallback_source or "gallery_dl"
    from plugins.builtin.gallery_dl._sites import get_site_config as _get_site_config
    _cfg = _get_site_config(raw_source)
    source = _cfg.source_id
    source_id = _resolve_source_id(meta, _cfg, dest_dir.name)

    # Tag extraction and normalization
    tags = _extract_tags(dest_dir, meta, source=source)
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
        category=meta.get("gallery_category") or "",
        language=meta.get("lang") or meta.get("language", ""),
        tags=tags,
        artist_id=artist_id,
        posted_at=posted_at,
        uploader=meta.get("uploader", ""),
        extra={},
    )


def _extract_tags(gallery_path: Path, metadata: dict, source: str | None = None) -> list[str]:
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

    # Extract hashtags from content for social platforms
    if source:
        from plugins.builtin.gallery_dl._sites import get_site_config
        cfg = get_site_config(source)
        if cfg.category == "social":
            import re
            content = metadata.get("content") or metadata.get("description") or ""
            seen = {t.lower() for t in tags}
            for ht in re.findall(r"#([\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff\uac00-\ud7af]+)", content):
                tag_str = f"general:{ht.lower()}"
                if tag_str not in seen:
                    tags.append(tag_str)
                    seen.add(tag_str)

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
    elif strategy == "pixiv_user":
        pixiv_uid = meta.get("pixiv_user_id")
        if pixiv_uid:
            return f"pixiv:{pixiv_uid}"
        uploader = meta.get("uploader", "")
        if uploader:
            return f"pixiv:{uploader}"
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
