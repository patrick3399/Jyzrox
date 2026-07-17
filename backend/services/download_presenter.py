"""Serialization of download jobs shared by download and subscription routers.

Extracted from routers/download.py so routers no longer cross-import each
other's private helpers (architecture risk #1).
"""

from db.models import DownloadJob, Gallery


def serialize_download_job(j: DownloadJob, gallery: Gallery | None = None) -> dict:
    d = {
        "id": str(j.id),
        "url": j.url,
        "source": j.source,
        "status": j.status,
        "progress": j.progress,
        "options": j.options or {},
        "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "retry_count": j.retry_count,
        "max_retries": j.max_retries,
        "next_retry_at": j.next_retry_at.isoformat() if j.next_retry_at else None,
        "gallery_id": j.gallery_id,
        "subscription_id": j.subscription_id,
    }
    if gallery:
        d["gallery_source"] = gallery.source
        d["gallery_source_id"] = gallery.source_id
    return d
