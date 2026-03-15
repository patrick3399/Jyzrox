"""Pixiv metadata parsing for the Parseable protocol."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from plugins.models import GalleryImportData

logger = logging.getLogger(__name__)


def parse_pixiv_import(dest_dir: Path, raw_meta: dict | None = None) -> GalleryImportData:
    """Parse a Pixiv gallery directory into GalleryImportData."""
    meta = raw_meta or {}
    if not meta:
        meta_file = dest_dir / "metadata.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[pixiv_metadata] failed to read metadata.json: %s", exc)

    tags: list[str] = []
    raw = meta.get("tags")
    if isinstance(raw, dict):
        for ns, names in raw.items():
            tags.extend(f"{ns}:{n}" for n in names)
    elif isinstance(raw, list):
        tags.extend(raw)

    # Artist ID: prefer numeric pixiv_user_id over display name
    artist_id: str | None = None
    pixiv_user_id = meta.get("pixiv_user_id")
    uploader = meta.get("uploader", "")
    if pixiv_user_id:
        artist_id = f"pixiv:{pixiv_user_id}"
    elif uploader:
        artist_id = f"pixiv:{uploader}"

    posted_at: datetime | None = None
    raw_date = meta.get("date") or meta.get("posted")
    if raw_date:
        try:
            if isinstance(raw_date, int | float):
                posted_at = datetime.fromtimestamp(raw_date, tz=UTC)
            else:
                posted_at = datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError, OverflowError):
            pass

    return GalleryImportData(
        source="pixiv",
        source_id=str(meta.get("id") or dest_dir.name),
        title=meta.get("title") or dest_dir.name,
        title_jpn="",
        category=meta.get("type", ""),
        language="",
        tags=tags,
        artist_id=artist_id,
        posted_at=posted_at,
        uploader=uploader,
        extra={
            "pixiv_user_id": meta.get("pixiv_user_id"),
            "pixiv_illust_type": meta.get("pixiv_illust_type", "illust"),
            "total_bookmarks": meta.get("total_bookmarks", 0),
            "total_view": meta.get("total_view", 0),
        },
    )
