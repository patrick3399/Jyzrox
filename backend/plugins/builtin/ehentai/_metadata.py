"""E-Hentai metadata parsing for the Parseable protocol."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from plugins.models import GalleryImportData

logger = logging.getLogger(__name__)


def parse_eh_import(dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
    """Parse an EH gallery directory into GalleryImportData."""
    meta = raw_meta or {}
    if not meta:
        meta_file = dest_dir / "metadata.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[eh_metadata] failed to read metadata.json: %s", exc)

    tags = _extract_tags(dest_dir, meta)

    # Artist extraction from tags
    artist_id: str | None = None
    for tag in tags:
        if tag.startswith("artist:"):
            artist_id = f"ehentai:{tag[7:]}"
            break

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
        source="ehentai",
        source_id=str(meta.get("gid") or meta.get("gallery_id") or dest_dir.name),
        title=meta.get("title") or meta.get("title_en") or dest_dir.name,
        title_jpn=meta.get("title_jpn") or "",
        category=meta.get("gallery_category") or "",
        language=meta.get("lang") or meta.get("language") or "",
        tags=tags,
        artist_id=artist_id,
        posted_at=posted_at,
        uploader=meta.get("uploader") or "",
        extra={"token": meta.get("token") or ""},
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

    if not tags:
        tags_file = gallery_path / "tags.txt"
        if tags_file.exists():
            try:
                tags = [t.strip() for t in tags_file.read_text(encoding="utf-8").splitlines() if t.strip()]
            except OSError:
                pass

    return tags
