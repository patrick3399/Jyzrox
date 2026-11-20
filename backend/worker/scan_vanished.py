"""Vanished link-gallery handling for library scan jobs."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.sql import select

from db.models import Gallery, Image
from services.gallery_lifecycle import invalidate_sources_cache, mark_trashed
from services.link_sync import library_root_available
from worker.constants import logger
from worker.scan_common import _page_file_exists

# How long a link gallery whose folder is gone waits for it before going to trash.
VANISHED_LINK_GALLERY_GRACE = timedelta(days=30)


def _link_source_vanished(gallery: Gallery, images: list[Image]) -> bool:
    """Return True when a link gallery's folder and every page file are gone.

    From the database this is indistinguishable from a folder renamed while the
    watcher was not looking, so it must not be treated as a deletion (ADR 0027).
    Callers have already ruled out an unavailable library root.
    """
    if gallery.import_mode != "link" or not gallery.source_path or not images:
        return False
    if Path(gallery.source_path).is_dir():
        return False
    return not any(_page_file_exists(img) for img in images)


def _hold_vanished_link_gallery(gallery: Gallery) -> str | None:
    """Keep a vanished link gallery intact, trashing it once the grace period ends.

    ``last_scanned_at`` is set when the gallery is first held and then left alone,
    so it dates the grace period without a new column. Clearing the directory
    mtime makes the next sync run the full diff that restores the gallery if the
    folder comes back. Returns ``"held"`` or ``"trashed"`` on a state change.
    """
    now = datetime.now(UTC)
    noticed_at = gallery.last_scanned_at
    if gallery.download_status != "missing" or noticed_at is None:
        gallery.download_status = "missing"
        gallery.source_dir_mtime_ns = None
        gallery.last_scanned_at = now
        logger.warning(
            "[link_source] gallery_id=%d: source %s is gone; keeping the gallery for %d days",
            gallery.id,
            gallery.source_path,
            VANISHED_LINK_GALLERY_GRACE.days,
        )
        return "held"
    if noticed_at.tzinfo is None:
        noticed_at = noticed_at.replace(tzinfo=UTC)
    if now - noticed_at < VANISHED_LINK_GALLERY_GRACE:
        return None
    mark_trashed([gallery], reason="source_missing", actor_user_id=None, now=now)
    logger.warning(
        "[link_source] gallery_id=%d: source %s stayed gone; moved to trash", gallery.id, gallery.source_path
    )
    return "trashed"


async def _announce_vanished_link_galleries(outcomes: list[tuple[int, str]]) -> None:
    from core.events import EventType, emit_safe

    for gallery_id, outcome in outcomes:
        if outcome == "trashed":
            await emit_safe(EventType.GALLERY_DELETED, resource_type="gallery", resource_id=gallery_id)
        else:
            await emit_safe(
                EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=gallery_id, reason="link_source_missing"
            )
    if any(outcome == "trashed" for _, outcome in outcomes):
        await invalidate_sources_cache()


async def _vanished_link_source_paths(session) -> list[str]:
    """List the source folders of live link galleries that no longer exist."""
    rows = (
        await session.execute(
            select(Gallery.source_path, Gallery.library_path).where(
                Gallery.source == "local",
                Gallery.import_mode == "link",
                Gallery.source_path.is_not(None),
                Gallery.deleted_at.is_(None),
            )
        )
    ).all()

    def _scan() -> list[str]:
        # An unavailable root makes all of its folders look gone; none of them moved.
        available: dict[str | None, bool] = {}
        vanished: list[str] = []
        for source_path, library_path in rows:
            if library_path not in available:
                available[library_path] = library_root_available(library_path)
            if available[library_path] and not os.path.isdir(source_path):
                vanished.append(source_path)
        return vanished

    return await asyncio.to_thread(_scan)


async def _reconnect_vanished_gallery(
    ctx: dict, session, directory: Path, vanished: list[str], *, watcher_origin: bool
) -> dict | None:
    """Try to attach a newly seen folder to the gallery it was renamed from.

    Returns the job result when the folder is accounted for (moved, or refused
    because the match is ambiguous), or None when discovery should import it.
    """
    from worker.scan_paths import reconcile_library_path_job  # deferred: scan_paths imports this module

    if not vanished:
        return None
    # The move runs in its own session; publish this one's work before it starts.
    await session.commit()
    result = await reconcile_library_path_job(
        ctx, old_paths=vanished, new_path=str(directory), watcher_origin=watcher_origin
    )
    if result.get("status") == "conflict" and result.get("reason") == "content_mismatch":
        return None
    if result.get("status") == "moved":
        logger.info(
            "[link_source] gallery_id=%s: reconnected %s -> %s",
            result.get("gallery_id"),
            result.get("old_path"),
            result.get("new_path"),
        )
    return result
