"""Safe lifecycle helpers for content-addressed thumbnail directories.

Thumbnail files belong to a Blob SHA, not to an individual Gallery.  Every
destructive caller must therefore verify the live Image references before
removing a thumbnail directory.  Keeping that rule here prevents gallery
rescan, trash cleanup, and progressive-import rollback from implementing
slightly different (and occasionally unsafe) ref-count checks.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Blob, Image
from services.cas import thumb_dir

logger = logging.getLogger(__name__)


def _unique_sha256s(sha256s: Iterable[str]) -> list[str]:
    return sorted({sha256 for sha256 in sha256s if sha256})


async def synchronize_blob_reference_counts(
    db: AsyncSession,
    sha256s: Iterable[str],
) -> tuple[set[str], bool]:
    """Repair ref-count drift and return SHAs with no live Image references.

    The denormalized ``Blob.ref_count`` remains useful for inexpensive status
    queries, but it is not authoritative for destructive filesystem cleanup.
    The Image table is checked every time a thumbnail directory may be removed.
    """

    unique_shas = _unique_sha256s(sha256s)
    if not unique_shas:
        return set(), False

    rows = (
        await db.execute(
            select(
                Blob.sha256,
                Blob.ref_count,
                func.count(Image.id).label("actual_refs"),
            )
            .outerjoin(Image, Image.blob_sha256 == Blob.sha256)
            .where(Blob.sha256.in_(unique_shas))
            .group_by(Blob.sha256, Blob.ref_count)
        )
    ).all()

    unreferenced: set[str] = set()
    repaired = False
    for sha256, ref_count, actual_refs in rows:
        actual = int(actual_refs)
        if int(ref_count or 0) != actual:
            logger.warning(
                "[thumbnail_lifecycle] ref_count drift for %s: %s -> %d",
                sha256[:12],
                ref_count,
                actual,
            )
            await db.execute(update(Blob).where(Blob.sha256 == sha256).values(ref_count=actual))
            repaired = True
        if actual == 0:
            unreferenced.add(sha256)

    return unreferenced, repaired


def remove_thumbnail_dirs_sync(
    sha256s: Iterable[str],
    *,
    directory_resolver: Callable[[str], Path] = thumb_dir,
) -> int:
    """Remove thumbnail directories for already-verified unreferenced SHAs."""

    removed = 0
    for sha256 in _unique_sha256s(sha256s):
        directory = directory_resolver(sha256)
        if not directory.exists():
            continue
        try:
            shutil.rmtree(str(directory))
            removed += 1
        except OSError as exc:
            logger.warning("[thumbnail_lifecycle] failed to remove %s: %s", directory, exc)
    return removed


async def cleanup_unreferenced_thumbnails(
    db: AsyncSession,
    sha256s: Iterable[str],
    *,
    commit_repairs: bool = True,
    directory_resolver: Callable[[str], Path] = thumb_dir,
) -> set[str]:
    """Delete thumbnails only when the Blob has zero actual Image references.

    Database repairs are committed before filesystem deletion.  A crash at the
    boundary can leave an orphan directory, which reconciliation can safely
    remove later; it cannot make a referenced image lose its thumbnails.
    """

    unreferenced, repaired = await synchronize_blob_reference_counts(db, sha256s)
    if commit_repairs and repaired:
        await db.commit()
    if unreferenced:
        await asyncio.to_thread(
            remove_thumbnail_dirs_sync,
            unreferenced,
            directory_resolver=directory_resolver,
        )
    return unreferenced
