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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Blob, Image, WorkbenchOperation
from services.cas import cas_path, library_dir
from services.image_purge_helpers import (
    _blob_ref_counts,
    _chunks,
    _count_by_sha,
    _exclude_insert,
    _gc_unreferenced_blobs,
    _load_purgeable_gallery,
    _unlink_library_links_sync,
)

logger = logging.getLogger(__name__)


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
