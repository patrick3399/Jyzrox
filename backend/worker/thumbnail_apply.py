"""Result application and ordering helpers for thumbnail jobs."""

from db.models import Image
from worker.thumbnail_pool import _ThumbnailResult


def _apply_thumbnail_result(blob, result: _ThumbnailResult) -> None:
    blob.width = result.width
    blob.height = result.height
    blob.duration = result.duration
    if result.phash is not None:
        if blob.phash_int != result.phash_int:
            blob.dedup_scanned_threshold = None
            blob.dedup_scanned_phash_int = None
            blob.dedup_scanned_version = None
        blob.phash = result.phash
        blob.phash_int = result.phash_int
        blob.phash_q0 = result.phash_q0
        blob.phash_q1 = result.phash_q1
        blob.phash_q2 = result.phash_q2
        blob.phash_q3 = result.phash_q3
    if result.thumbhash is not None:
        blob.thumbhash = result.thumbhash


def _cover_first(images: list[Image], cover_page: str) -> list[Image]:
    if not images:
        return []
    cover_index = len(images) - 1 if cover_page == "last" else 0
    cover = images[cover_index]
    return [cover, *(img for idx, img in enumerate(images) if idx != cover_index)]
