"""Transactional Gallery merge implementation for the Library Workbench."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Blob,
    DownloadJob,
    Gallery,
    GalleryMetadataChange,
    GalleryMetadataFieldState,
    Image,
)
from services.gallery_lifecycle import mark_trashed
from services.workbench_merge_copy import SIMILAR_PHASH_DISTANCE, _copy_images, _copy_source_items, _hamming_distance
from services.workbench_merge_relations import _merge_gallery_relations, _merge_read_progress
from services.workbench_metadata import load_writable_galleries, metadata_json_value

MERGE_SCALAR_FIELDS = frozenset(
    {"title", "title_jpn", "category", "language", "artist_id", "uploader", "visibility", "posted_at", "rating"}
)
ACTIVE_DOWNLOAD_STATUSES = ("queued", "running", "paused")


PENDING_MERGE_DETAIL = "Wait for pages to finish processing before merging galleries"


async def count_pending_pages(db: AsyncSession, gallery_ids: Sequence[int]) -> int:
    """Count pages with no blob yet (link pages still waiting for their hash).

    Merging copies pages by sha256 and moves blob references, so a page without
    a blob cannot take part until the hash job has filled it in.
    """
    if not gallery_ids:
        return 0
    return (
        await db.execute(
            select(func.count())
            .select_from(Image)
            .where(Image.gallery_id.in_(list(gallery_ids)), Image.blob_sha256.is_(None))
        )
    ).scalar_one()


async def validate_merge_selection(
    db: AsyncSession,
    gallery_ids: Sequence[int],
    target_id: int,
    auth: dict,
    *,
    lock_rows: bool = False,
) -> tuple[Gallery, list[Gallery]]:
    unique_ids = list(dict.fromkeys(gallery_ids))
    if not 2 <= len(unique_ids) <= 50:
        raise HTTPException(status_code=400, detail="Merge requires between 2 and 50 galleries")
    if target_id not in unique_ids:
        raise HTTPException(status_code=400, detail="Target gallery must be included in the selection")
    galleries = await load_writable_galleries(db, unique_ids, auth, lock_rows=lock_rows)
    by_id = {gallery.id: gallery for gallery in galleries}
    target = by_id[target_id]
    sources = [by_id[gallery_id] for gallery_id in unique_ids if gallery_id != target_id]

    active_count = (
        await db.execute(
            select(func.count())
            .select_from(DownloadJob)
            .where(DownloadJob.gallery_id.in_(unique_ids), DownloadJob.status.in_(ACTIVE_DOWNLOAD_STATUSES))
        )
    ).scalar_one()
    if active_count:
        raise HTTPException(status_code=409, detail="Cancel active downloads before merging galleries")
    if await count_pending_pages(db, unique_ids):
        raise HTTPException(status_code=409, detail=PENDING_MERGE_DETAIL)
    return target, sources


async def preview_gallery_merge(
    db: AsyncSession,
    gallery_ids: Sequence[int],
    target_id: int,
    auth: dict,
) -> dict[str, Any]:
    target, sources = await validate_merge_selection(db, gallery_ids, target_id, auth)
    ordered = [target, *sources]
    image_rows = (
        await db.execute(
            select(Image.gallery_id, Image.blob_sha256, Blob.phash_int)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.gallery_id.in_([gallery.id for gallery in ordered]))
        )
    ).all()
    target_hashes = {row.blob_sha256 for row in image_rows if row.gallery_id == target.id}
    target_phashes = {
        row.blob_sha256: row.phash_int
        for row in image_rows
        if row.gallery_id == target.id and row.phash_int is not None
    }
    exact = 0
    similar = 0
    added = 0
    seen = set(target_hashes)
    phashes = dict(target_phashes)
    for source in sources:
        for row in (candidate for candidate in image_rows if candidate.gallery_id == source.id):
            if row.blob_sha256 in seen:
                exact += 1
                continue
            if row.phash_int is not None and any(
                _hamming_distance(row.phash_int, other) <= SIMILAR_PHASH_DISTANCE for other in phashes.values()
            ):
                similar += 1
            seen.add(row.blob_sha256)
            if row.phash_int is not None:
                phashes[row.blob_sha256] = row.phash_int
            added += 1

    conflicts = {
        field_name: [{"gallery_id": gallery.id, "value": getattr(gallery, field_name)} for gallery in ordered]
        for field_name in MERGE_SCALAR_FIELDS
        if len({repr(getattr(gallery, field_name)) for gallery in ordered}) > 1
    }
    return {
        "target_id": target.id,
        "source_ids": [source.id for source in sources],
        "scalar_conflicts": conflicts,
        "images": {"add": added, "exact_sha_skipped": exact, "similar_kept_for_review": similar},
        "result": {
            "source_routes": "404",
            "sources_moved_to_trash": len(sources),
            "restore_reverses_merge": False,
        },
    }


async def execute_gallery_merge(
    db: AsyncSession,
    gallery_ids: Sequence[int],
    target_id: int,
    scalar_sources: Mapping[str, int],
    auth: dict,
    operation_id: UUID,
) -> dict[str, Any]:
    target, sources = await validate_merge_selection(db, gallery_ids, target_id, auth, lock_rows=True)
    selected = {gallery.id: gallery for gallery in [target, *sources]}
    unknown_fields = set(scalar_sources) - MERGE_SCALAR_FIELDS
    if unknown_fields:
        raise HTTPException(status_code=400, detail=f"Unsupported merge fields: {', '.join(sorted(unknown_fields))}")
    if any(gallery_id not in selected for gallery_id in scalar_sources.values()):
        raise HTTPException(status_code=400, detail="Scalar source must be one of the selected galleries")

    source_item_map = await _copy_source_items(db, target.id, sources)
    image_map, copied, exact, similar = await _copy_images(db, target, sources, source_item_map)
    await _merge_gallery_relations(db, target, sources)
    await _merge_read_progress(db, target.id, [source.id for source in sources], image_map)

    now = datetime.now(UTC)
    for field_name, selected_gallery_id in scalar_sources.items():
        new_value = getattr(selected[selected_gallery_id], field_name)
        old_value = getattr(target, field_name)
        if old_value == new_value:
            continue
        setattr(target, field_name, new_value)
        state = await db.get(GalleryMetadataFieldState, (target.id, field_name))
        if state is None:
            state = GalleryMetadataFieldState(gallery_id=target.id, field_name=field_name)
            db.add(state)
        state.origin = "merge"
        state.locked = True
        state.updated_by_user_id = auth["user_id"]
        state.updated_at = now
        db.add(
            GalleryMetadataChange(
                gallery_id=target.id,
                field_name=field_name,
                old_value=metadata_json_value(old_value),
                new_value=metadata_json_value(new_value),
                origin="merge",
                actor_user_id=auth["user_id"],
                operation_id=operation_id,
            )
        )

    target.pages = (
        await db.execute(
            select(func.count()).select_from(Image).where(Image.gallery_id == target.id, Image.visibility == "active")
        )
    ).scalar_one()
    target.metadata_updated_at = now
    mark_trashed(
        sources,
        reason="merged",
        actor_user_id=auth["user_id"],
        merged_into_gallery_id=target.id,
        now=now,
    )

    return {
        "target_id": target.id,
        "source_ids": [source.id for source in sources],
        "images_added": copied,
        "exact_sha_skipped": exact,
        "similar_kept_for_review": similar,
        "source_routes": "404",
    }
