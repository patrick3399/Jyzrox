"""Recovery for local imports interrupted by worker death (HR-019).

A container OOM kill delivers SIGKILL, which Python cannot intercept, so
`local_import_job` never reaches its terminal-status write: the gallery keeps
`download_status='importing'` and `pages = NULL` forever. Neither existing scan
path recovers it — `auto_discover_job` skips any `(source, source_id)` already
present, and `rescan_library_job` rewrites `gallery.pages` only inside its
`if removed:` branch, which never runs for a gallery that has no images yet.

Recovery therefore has to run out of band. Worker startup is the natural
trigger: it is exactly the moment after the process death that stranded the
rows in the first place.
"""

from sqlalchemy import select

import core.queue
from core.database import AsyncSessionLocal
from db.models import Gallery
from worker.constants import logger


async def requeue_orphaned_imports(ctx: dict) -> dict:
    """Re-enqueue local imports left mid-flight by a previous worker process."""
    async with AsyncSessionLocal() as session:
        orphans = (
            (
                await session.execute(
                    select(Gallery).where(
                        Gallery.source == "local",
                        Gallery.download_status == "importing",
                        # HR-014: never resurrect a trashed gallery. A gallery
                        # can be trashed while its import job is still queued,
                        # so this state legitimately coexists with deleted_at.
                        Gallery.deleted_at.is_(None),
                        # Without a source directory there is nothing to import.
                        Gallery.source_path.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        pending = [(row.id, row.source_path, row.import_mode or "link") for row in orphans]

    for gallery_id, source_dir, mode in pending:
        # SAQ's enqueue script skips a job id already in the incomplete set, so
        # replaying recovery cannot double-queue a gallery whose job survived.
        await core.queue.enqueue(
            "local_import_job",
            source_dir=source_dir,
            mode=mode,
            gallery_id=gallery_id,
            _timeout=3600,
            _job_id=f"local-import:{gallery_id}",
        )
        logger.info("[import_recovery] requeued stranded import gallery_id=%d", gallery_id)

    if pending:
        logger.warning("[import_recovery] requeued %d stranded local import(s)", len(pending))

    return {
        "status": "done",
        "requeued": len(pending),
        "gallery_ids": [gallery_id for gallery_id, _, _ in pending],
    }
