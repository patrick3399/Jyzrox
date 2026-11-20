"""Background hash pass for link galleries (ADR 0015): attach sha256 + Blob to pending pages."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update

import core.queue
from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import ExcludedBlob, Gallery, Image
from services.cas import increment_ref_count, store_blob
from services.link_sync_plan import _active_page_count, _pending_count
from services.source_identity import SourceFileChangedError, SourceFileIdentity, hash_file_with_identity

logger = logging.getLogger(__name__)


async def enqueue_link_hash(gallery_id: int) -> None:
    """Queue the hash pass; SAQ drops the enqueue while one is already queued or running."""
    await core.queue.enqueue("link_hash_job", gallery_id=gallery_id, _timeout=14400, _job_id=f"link-hash:{gallery_id}")


# Pages hashed per transaction. Files in a chunk are hashed in parallel threads.
LINK_HASH_CHUNK = 16


@dataclass(slots=True)
class LinkHashResult:
    status: str
    hashed: int = 0
    failed: int = 0
    remaining: int = 0
    pages: int | None = None


async def _hash_path(path: str) -> tuple[str, SourceFileIdentity] | None:
    try:
        return await asyncio.to_thread(hash_file_with_identity, Path(path))
    except (OSError, SourceFileChangedError) as exc:
        logger.warning("[link_hash] skipping %s: %s", path, exc)
        return None


async def hash_pending_images(gallery_id: int) -> LinkHashResult:
    """Attach sha256 + Blob to every pending page of a link gallery.

    Needs no gallery lock: each page is completed with an UPDATE that only
    matches while the row is still pending and still carries the fingerprint
    that was hashed, so a concurrent sync or a second hash pass cannot be
    overwritten, and the ref_count is taken only when that UPDATE matched.
    """
    result = LinkHashResult(status="done")
    attempted: set[int] = set()
    last_event = 0.0

    while True:
        async with AsyncSessionLocal() as session:
            gallery = await session.get(Gallery, gallery_id)
            if gallery is None:
                return LinkHashResult(status="not_found")
            if gallery.deleted_at is not None:
                # HR-014: only trash GC may touch a trashed gallery.
                return LinkHashResult(status="skipped_trashed")
            if gallery.import_mode != "link":
                return LinkHashResult(status="not_link")

            stmt = (
                select(Image.id, Image.external_path, Image.source_size, Image.source_mtime_ns)
                .where(
                    Image.gallery_id == gallery_id,
                    Image.blob_sha256.is_(None),
                    Image.external_path.is_not(None),
                )
                .order_by(Image.page_num)
                .limit(LINK_HASH_CHUNK)
            )
            if attempted:
                stmt = stmt.where(Image.id.not_in(attempted))
            rows = (await session.execute(stmt)).all()
            if not rows:
                break

            excluded = set(
                (await session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
                .scalars()
                .all()
            )
            hashed = await asyncio.gather(*(_hash_path(row.external_path) for row in rows))

            # One transaction per chunk. Per page the order is: blob upsert +
            # location (flushed, the composite FK is not deferrable) -> image
            # UPDATE -> ref_count increment, only when the UPDATE matched.
            for row, outcome in zip(rows, hashed, strict=True):
                attempted.add(row.id)
                if outcome is None:
                    result.failed += 1
                    continue
                sha256, identity = outcome
                if (identity.size, identity.mtime_ns) != (row.source_size, row.source_mtime_ns):
                    # The file changed after it was registered. The next sync
                    # records the new fingerprint; hashing it now would attach
                    # a blob the row's fingerprint does not describe.
                    result.failed += 1
                    continue
                await store_blob(
                    Path(row.external_path), sha256, session, storage="external", external_path=row.external_path
                )
                await session.flush()
                values: dict = {"blob_sha256": sha256}
                if sha256 in excluded:
                    # Hidden by the user. Keep the row so the file is not
                    # registered again on the next sync.
                    values["visibility"] = "excluded"
                updated = await session.execute(
                    update(Image)
                    .where(
                        Image.id == row.id,
                        Image.blob_sha256.is_(None),
                        Image.source_size == row.source_size,
                        Image.source_mtime_ns == row.source_mtime_ns,
                    )
                    .values(**values)
                )
                if updated.rowcount == 1:
                    await increment_ref_count(sha256, session)
                    result.hashed += 1
            await session.commit()

        if time.monotonic() - last_event >= 1.0:
            last_event = time.monotonic()
            await emit_safe(
                EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=gallery_id, reason="link_hash_progress"
            )

    was_importing = False
    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if gallery is None or gallery.deleted_at is not None:
            return result
        result.remaining = await _pending_count(session, gallery_id)
        result.pages = await _active_page_count(session, gallery_id)
        was_importing = gallery.download_status == "importing"
        # Gallery changes come last: the blob statements above are already committed.
        gallery.pages = result.pages
        if result.pages == 0:
            if was_importing:
                gallery.download_status = "failed"
        elif result.remaining == 0:
            if gallery.download_status in ("importing", "partial", "failed"):
                gallery.download_status = "complete"
        elif was_importing:
            gallery.download_status = "partial"
        gallery.metadata_updated_at = func.now()
        await session.commit()

    if result.hashed:
        await core.queue.enqueue(
            "cover_thumbnail_job", gallery_id=gallery_id, _timeout=300, _job_id=f"cover-thumbnail:{gallery_id}"
        )
        await core.queue.enqueue(
            "thumbnail_job", gallery_id=gallery_id, _timeout=3600, _job_id=f"thumbnail:{gallery_id}"
        )
    await emit_safe(
        EventType.GALLERY_UPDATED,
        resource_type="gallery",
        resource_id=gallery_id,
        reason="link_hash",
        pages=result.pages,
        pending=result.remaining,
    )
    if was_importing:
        await emit_safe(
            EventType.IMPORT_COMPLETED,
            resource_type="gallery",
            resource_id=gallery_id,
            pages=result.pages,
            source="local",
        )
    return result
