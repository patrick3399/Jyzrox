"""Gallery metadata sidecar (info.json) for the library symlink tree.

The library tree (/data/library/{source}/{safe_source_id}/) is the
disaster-recovery escape hatch: if the database is lost, galleries can still
be copied out of it (relative symlinks resolve into CAS). Directory names are
source ids though — without the DB there is no title/artist/tag information.
The sidecar writes that metadata as a small JSON file next to the symlinks so
a recovered gallery stays identifiable.

The sidecar is metadata about the gallery, not gallery content: reconciliation
must not treat it as a library file, and the explorer file listing hides it.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from db.models import Gallery
from services.cas import library_dir

logger = logging.getLogger(__name__)

SIDECAR_FILENAME = "info.json"


def sidecar_payload_from_gallery(gallery: Gallery) -> dict[str, Any]:
    """Build the sidecar payload from a Gallery row."""
    posted_at = gallery.posted_at
    return {
        "title": gallery.title,
        "title_jpn": gallery.title_jpn,
        "source": gallery.source,
        "source_id": gallery.source_id,
        "category": gallery.category,
        "language": gallery.language,
        "uploader": gallery.uploader,
        "artist_id": gallery.artist_id,
        "pages": gallery.pages,
        "source_pages": gallery.source_pages,
        "source_url": gallery.source_url,
        "tags": list(gallery.tags_array or []),
        "posted_at": posted_at.isoformat() if posted_at is not None else None,
    }


async def write_gallery_sidecar(source: str, source_id: str, payload: dict[str, Any]) -> bool:
    """Write info.json into the gallery's library directory (best-effort).

    Atomic (temp file + os.replace) so a crash never leaves truncated JSON.
    Returns True when written; every failure is logged and swallowed — the
    sidecar is a recovery aid and must never fail the import or download that
    writes it.
    """
    tmp = None
    try:
        target_dir = library_dir(source, source_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["written_at"] = datetime.now(UTC).isoformat()
        tmp = target_dir / f".{SIDECAR_FILENAME}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target_dir / SIDECAR_FILENAME)
        return True
    except Exception as exc:
        logger.warning("[sidecar] failed to write %s/%s %s: %s", source, source_id, SIDECAR_FILENAME, exc)
        try:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
