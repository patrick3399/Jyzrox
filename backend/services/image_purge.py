"""Permanent deletion of user-hidden images to reclaim CAS disk space.

Hiding an image only flips ``visibility``; its bytes stay in CAS.  Purging
removes the Image row for good, records the content hash in ``excluded_blobs``
so downloads and imports never bring it back, and frees the bytes when no other
Image row references the blob.

Ordering rules (see ``docs/ref/high-risk-invariants.md``):

* Blob rows are locked before anything touches a gallery row (BE-T24).
* The database transaction commits before any byte is unlinked (HR-003 pattern
  used by reconciliation Phase 3); a crash leaves at worst an orphan file that
  weekly reconciliation removes, never a live row without its bytes.
* Only ``storage='cas'`` blobs are ever reclaimed.  Images bound to a linked
  external folder are the user's own files and are skipped and reported.
* Post-commit cleanup failures are logged and swallowed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, has_gallery_write_access
from db.models import Blob, DownloadJob, ExcludedBlob, Gallery, Image, WorkbenchOperation
from services.cas import cas_path, library_dir
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


async def purge_hidden_images(
    db: AsyncSession,
    gallery_id: int,
    image_ids: list[int] | None,
    auth: dict,
    *,
    dry_run: bool,
    operation_id: uuid.UUID | None = None,
) -> dict:
    """Permanently delete ``user_hidden`` CAS images of one gallery.

    ``image_ids=None`` means every hidden image of the gallery.  Raises 404
    (missing or inaccessible), 403 (no write access) or 409 (trashed gallery or
    active download).  The returned dict is the response body.
    """
    gallery = await _load_purgeable_gallery(db, gallery_id, auth)
    source, source_id = gallery.source, gallery.source_id

    stmt = (
        select(
            Image.id,
            Image.visibility,
            Image.filename,
            Image.external_path,
            Image.blob_sha256,
            Blob.storage,
            Blob.extension,
            Blob.file_size,
        )
        .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
        .where(Image.gallery_id == gallery.id)
    )
    requested = list(dict.fromkeys(image_ids)) if image_ids is not None else None
    if requested is None:
        stmt = stmt.where(Image.visibility == "user_hidden")
        rows = (await db.execute(stmt)).all()
    else:
        rows = []
        for chunk in _chunks(requested):
            rows.extend((await db.execute(stmt.where(Image.id.in_(chunk)))).all())

    skipped_missing = 0 if requested is None else len(requested) - len(rows)
    skipped_not_hidden = skipped_pending = skipped_external = 0
    candidates = []
    for row in rows:
        if row.visibility != "user_hidden":
            skipped_not_hidden += 1
        elif row.blob_sha256 is None:
            skipped_pending += 1
        elif row.storage != "cas" or row.external_path is not None:
            skipped_external += 1
        else:
            candidates.append(row)

    result: dict[str, Any] = {
        "gallery_id": gallery.id,
        "dry_run": dry_run,
        "purgeable": len(candidates),
        "purged": 0,
        "reclaim_bytes": 0,
        "shared_kept": 0,
        "skipped_external": skipped_external,
        "skipped_not_hidden": skipped_not_hidden,
        "skipped_pending": skipped_pending,
        "skipped_missing": skipped_missing,
        "blobs_deleted": 0,
        "operation_id": None,
    }
    if not candidates:
        return result

    sizes = {row.blob_sha256: int(row.file_size or 0) for row in candidates}
    candidate_shas = sorted(sizes)

    if dry_run:
        refs = await _blob_ref_counts(db, candidate_shas)
        per_sha = _count_by_sha(candidates)
        freed = {sha for sha in candidate_shas if refs.get(sha, 0) - per_sha[sha] <= 0}
        result["reclaim_bytes"] = sum(sizes[sha] for sha in freed)
        result["shared_kept"] = sum(1 for row in candidates if row.blob_sha256 not in freed)
        return result

    started_at = datetime.now(UTC)
    # Blob rows first (BE-T24): this also blocks a concurrent import from
    # attaching a new Image to a blob while we decide whether it is unreferenced.
    for chunk in _chunks(candidate_shas):
        await db.execute(select(Blob.sha256).where(Blob.sha256.in_(chunk)).order_by(Blob.sha256).with_for_update())

    # Delete only rows that are still hidden: a concurrent restore wins.
    purged: list[Any] = []
    candidate_by_id = {row.id: row for row in candidates}
    candidate_id_list = list(candidate_by_id)
    for chunk in _chunks(candidate_id_list):
        deleted_ids = (
            await db.execute(
                delete(Image)
                .where(Image.id.in_(chunk), Image.gallery_id == gallery.id, Image.visibility == "user_hidden")
                .returning(Image.id)
                .execution_options(synchronize_session=False)
            )
        ).scalars()
        purged.extend(candidate_by_id[image_id] for image_id in deleted_ids)

    purged_per_sha = _count_by_sha(purged)
    if purged:
        now = datetime.now(UTC)
        # An ExcludedBlob row hides every Image of the gallery with that sha
        # (image_not_excluded_clause), so exclude only shas with no Image row
        # left in this gallery; a surviving twin must stay visible.
        still_in_gallery: set[str] = set()
        for chunk in _chunks(list(purged_per_sha)):
            still_in_gallery.update(
                (
                    await db.execute(
                        select(Image.blob_sha256).where(Image.gallery_id == gallery.id, Image.blob_sha256.in_(chunk))
                    )
                ).scalars()
            )
        exclude_rows = [
            {"gallery_id": gallery.id, "blob_sha256": sha, "excluded_at": now}
            for sha in purged_per_sha
            if sha not in still_in_gallery
        ]
        for chunk in _chunks(exclude_rows, 1000):
            await db.execute(_exclude_insert(db, list(chunk)))
        by_amount: dict[int, list[str]] = {}
        for sha, amount in purged_per_sha.items():
            by_amount.setdefault(amount, []).append(sha)
        for amount, shas in by_amount.items():
            for chunk in _chunks(shas):
                await db.execute(
                    update(Blob)
                    .where(Blob.sha256.in_(chunk))
                    .values(ref_count=case((Blob.ref_count > amount, Blob.ref_count - amount), else_=0))
                )

    remaining = await _blob_ref_counts(db, list(purged_per_sha))
    freed = {sha for sha in purged_per_sha if remaining.get(sha, 0) == 0}
    result["purged"] = len(purged)
    result["reclaim_bytes"] = sum(sizes[sha] for sha in freed)
    result["shared_kept"] = sum(1 for row in purged if row.blob_sha256 not in freed)

    operation = WorkbenchOperation(
        id=operation_id or uuid.uuid4(),
        user_id=auth["user_id"],
        kind="purge_images",
        status="completed",
        selection_count=len(requested) if requested is not None else len(candidates),
        params={
            "gallery_id": gallery.id,
            "all_hidden": requested is None,
            "image_ids": requested if requested is not None else [],
        },
        progress={key: result[key] for key in result if key not in {"gallery_id", "dry_run", "operation_id"}},
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    db.add(operation)
    await db.commit()
    result["operation_id"] = str(operation.id)

    # Post-commit cleanup: failures are logged and never raised.
    try:
        links: list[tuple[Path, Path]] = []
        directory = library_dir(source, source_id)
        for row in purged:
            name = row.filename or ""
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                continue
            links.append((directory / name, cas_path(row.blob_sha256, row.extension)))
        if links:
            await asyncio.to_thread(_unlink_library_links_sync, links)
    except Exception:
        logger.exception("[image_purge] library link cleanup failed for gallery %s", gallery_id)

    if freed:
        try:
            result["blobs_deleted"] = await _gc_unreferenced_blobs(db, sorted(freed))
        except Exception:
            logger.exception("[image_purge] blob cleanup failed for gallery %s", gallery_id)
    return result


def _count_by_sha(rows: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.blob_sha256] = counts.get(row.blob_sha256, 0) + 1
    return counts
