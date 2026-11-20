"""Helpers for permanent image purge (see ``services.image_purge``)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, has_gallery_write_access
from db.models import Blob, DownloadJob, ExcludedBlob, Gallery, Image
from services.cas import cas_path
from services.thumbnail_lifecycle import remove_thumbnail_dirs_sync
from services.workbench_merge import ACTIVE_DOWNLOAD_STATUSES

logger = logging.getLogger(__name__)


_CHUNK = 5000


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def _load_purgeable_gallery(db: AsyncSession, gallery_id: int, auth: dict) -> Gallery:
    """Return the gallery or raise 404 / 409 (trashed) / 403 (read-only)."""
    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        # The access filter hides trashed galleries; tell the owner (or an admin)
        # why the request is refused, and keep 404 for everyone else.
        trashed = (
            await db.execute(select(Gallery).where(Gallery.id == gallery_id, Gallery.deleted_at.is_not(None)))
        ).scalar_one_or_none()
        if trashed is not None and (
            auth.get("role") == "admin" or trashed.created_by_user_id in (None, auth["user_id"])
        ):
            raise HTTPException(status_code=409, detail="Gallery is in the trash")
        raise HTTPException(status_code=404, detail="Gallery not found")
    if not await has_gallery_write_access(db, gallery.id, gallery.created_by_user_id, auth):
        raise HTTPException(status_code=403, detail="Gallery write access is required")
    active_downloads = (
        await db.execute(
            select(func.count())
            .select_from(DownloadJob)
            .where(DownloadJob.gallery_id == gallery.id, DownloadJob.status.in_(ACTIVE_DOWNLOAD_STATUSES))
        )
    ).scalar_one()
    if active_downloads:
        raise HTTPException(status_code=409, detail="Cancel active downloads before purging images")
    return gallery


async def _blob_ref_counts(db: AsyncSession, shas: Sequence[str]) -> dict[str, int]:
    """Actual number of Image rows (any gallery, any visibility) per blob."""
    counts: dict[str, int] = {}
    for chunk in _chunks(list(shas)):
        rows = (
            await db.execute(
                select(Image.blob_sha256, func.count(Image.id))
                .where(Image.blob_sha256.in_(chunk))
                .group_by(Image.blob_sha256)
            )
        ).all()
        counts.update({sha: int(count) for sha, count in rows})
    return counts


def _exclude_insert(db: AsyncSession, rows: list[dict[str, Any]]):
    """INSERT ... ON CONFLICT DO NOTHING for the active dialect."""
    dialect = db.get_bind().dialect.name
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    return insert_fn(ExcludedBlob).values(rows).on_conflict_do_nothing(index_elements=["gallery_id", "blob_sha256"])


def _unlink_library_links_sync(links: list[tuple[Path, Path]]) -> int:
    """Unlink library symlinks that still point at the purged blob's CAS file."""
    removed = 0
    for link, target in links:
        try:
            if not link.is_symlink():
                continue
            if Path(os.path.realpath(link)) != Path(os.path.realpath(target)):
                continue
            link.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("[image_purge] failed to remove library link %s: %s", link, exc)
    return removed


def _unlink_cas_files_sync(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("[image_purge] failed to delete CAS file %s: %s", path, exc)
    return removed


async def _gc_unreferenced_blobs(db: AsyncSession, shas: Sequence[str]) -> int:
    """Delete blob rows left without Image rows, then their bytes and thumbnails.

    Each blob is re-checked under a row lock because an import may have attached
    a new Image since the purge committed.  The row deletion commits first.
    """
    deleted_total = 0
    for chunk in _chunks(sorted(set(shas)), 500):
        try:
            locked = (
                await db.execute(
                    select(Blob.sha256, Blob.extension, Blob.storage)
                    .where(Blob.sha256.in_(chunk))
                    .order_by(Blob.sha256)
                    .with_for_update()
                )
            ).all()
            refs = await _blob_ref_counts(db, [row.sha256 for row in locked])
            doomed = [row for row in locked if row.storage == "cas" and refs.get(row.sha256, 0) == 0]
            if not doomed:
                await db.rollback()
                continue
            doomed_shas = [row.sha256 for row in doomed]
            await db.execute(delete(Blob).where(Blob.sha256.in_(doomed_shas)))
            await db.commit()
        except Exception:
            logger.exception("[image_purge] blob GC failed; reconciliation will repair it")
            await db.rollback()
            continue

        files = [cas_path(row.sha256, row.extension) for row in doomed]
        try:
            await asyncio.to_thread(_unlink_cas_files_sync, files)
            await asyncio.to_thread(remove_thumbnail_dirs_sync, doomed_shas)
        except Exception:
            logger.exception("[image_purge] byte cleanup failed; reconciliation will repair it")
        deleted_total += len(doomed)
    return deleted_total


def _count_by_sha(rows: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.blob_sha256] = counts.get(row.blob_sha256, 0) + 1
    return counts
