"""gallery-dl per-job archive table preparation."""

import logging

from plugins.builtin.gallery_dl._archive import (
    ArchiveTableConflict,
    ensure_archive_table,
    ensure_repair_archive_table,
    repair_archive_tables,
)

logger = logging.getLogger(__name__)


async def _ensure_job_archive_table(url: str) -> str | None:
    """Create or upgrade the archive table this download writes to.

    gallery-dl would otherwise create a bare ``(entry)`` table for a category
    db/init.sql does not list, and its rows would stay unlinked until the next
    worker start upgraded the table. Returns an error when the category names a
    table that is not an archive; any other failure only logs, leaving the
    download as it was before this step existed.
    """
    from plugins.builtin.gallery_dl._identity import resolve_url_identity

    identity = resolve_url_identity(url)
    if identity is None:
        return None
    try:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            action = await ensure_archive_table(session, identity.category)
            await session.commit()
    except ArchiveTableConflict as exc:
        return str(exc)
    except Exception as exc:
        logger.warning("[gallery_dl] could not prepare archive table for %r: %s", identity.category, exc)
        return None
    if action != "ok":
        logger.info("[gallery_dl] archive table for %r %s", identity.category, action)
    return None


async def _prepare_repair_archive(url: str, job_id: str | None) -> str | None:
    """Create the per-job shadow archive a repair run reads and writes; returns its name.

    A repair fetches files the real archive already lists, so gallery-dl is
    pointed at an empty copy of that table instead. Its rows are merged into
    the real table when the run is kept (``ProgressiveImporter``).

    ``None`` means no shadow: the URL names no category, the job id is not a
    UUID, or the database refused. The run then has no archive at all, which is
    what a forced re-scan did before shadows existed; the importer's merge and
    drop find nothing to act on.
    """
    pair = repair_archive_tables(url, job_id)
    if pair is None:
        return None
    real, shadow = pair
    try:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await ensure_repair_archive_table(session, real, shadow)
            await session.commit()
    except Exception as exc:
        logger.warning("[gallery_dl] could not prepare repair archive %r for %s: %s", shadow, url, exc)
        return None
    return shadow
