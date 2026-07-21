"""Transactional Gallery merge implementation for the Library Workbench."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Blob,
    BlobRelationship,
    Collection,
    CollectionGallery,
    DownloadJob,
    ExcludedBlob,
    Gallery,
    GalleryMetadataChange,
    GalleryMetadataFieldState,
    GallerySourceItem,
    GalleryTag,
    Image,
    ImageTag,
    ReadProgress,
    UserFavorite,
    UserImageFavorite,
    UserRating,
    UserReadingList,
)
from services.cas import increment_ref_count
from services.workbench_metadata import load_writable_galleries, metadata_json_value

MERGE_SCALAR_FIELDS = frozenset(
    {"title", "title_jpn", "category", "language", "artist_id", "uploader", "visibility", "posted_at", "rating"}
)
ACTIVE_DOWNLOAD_STATUSES = ("queued", "running", "paused")
SIMILAR_PHASH_DISTANCE = 6


def _hamming_distance(left: int, right: int) -> int:
    mask = (1 << 64) - 1
    return ((left & mask) ^ (right & mask)).bit_count()


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
        field_name: [
            {"gallery_id": gallery.id, "value": getattr(gallery, field_name)}
            for gallery in ordered
        ]
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


async def _copy_source_items(
    db: AsyncSession,
    target_id: int,
    sources: Sequence[Gallery],
) -> dict[int, tuple[int, str]]:
    existing = (
        (await db.execute(select(GallerySourceItem).where(GallerySourceItem.gallery_id == target_id)))
        .scalars()
        .all()
    )
    used_ids = {item.source_item_id for item in existing}
    row_map: dict[int, tuple[int, str]] = {}
    for source in sources:
        items = (
            (
                await db.execute(
                    select(GallerySourceItem)
                    .where(GallerySourceItem.gallery_id == source.id)
                    .order_by(GallerySourceItem.source_position, GallerySourceItem.id)
                )
            )
            .scalars()
            .all()
        )
        for item in items:
            candidate = item.source_item_id
            if candidate in used_ids:
                candidate = f"{source.id}:{candidate}"
                suffix = 2
                while candidate in used_ids:
                    candidate = f"{source.id}:{item.source_item_id}:{suffix}"
                    suffix += 1
            copied = GallerySourceItem(
                gallery_id=target_id,
                source_item_id=candidate,
                source_item_url=item.source_item_url,
                title=item.title,
                published_at=item.published_at,
                page_count=item.page_count,
                source_position=item.source_position,
                source_seen_at=item.source_seen_at,
                status=item.status,
                metadata_json=dict(item.metadata_json or {}),
            )
            db.add(copied)
            await db.flush()
            row_map[item.id] = (copied.id, copied.source_item_id)
            used_ids.add(candidate)
    return row_map


async def _copy_images(
    db: AsyncSession,
    target: Gallery,
    sources: Sequence[Gallery],
    source_item_map: Mapping[int, tuple[int, str]],
) -> tuple[dict[int, int], int, int, int]:
    target_images = (
        (
            await db.execute(
                select(Image).where(Image.gallery_id == target.id).order_by(Image.page_num, Image.id).with_for_update()
            )
        )
        .scalars()
        .all()
    )
    target_by_sha = {image.blob_sha256: image for image in target_images}
    target_blobs = {
        blob.sha256: blob
        for blob in (
            (await db.execute(select(Blob).where(Blob.sha256.in_(list(target_by_sha) or [""]))))
            .scalars()
            .all()
        )
    }
    next_page = max((image.page_num for image in target_images), default=0) + 1
    image_map: dict[int, int] = {}
    copied_source_ids: set[int] = set()
    source_replacements: dict[int, int] = {}
    copied_count = 0
    exact_count = 0
    similar_count = 0

    existing_image_tags: dict[int, set[int]] = defaultdict(set)
    for row in (await db.execute(select(ImageTag).where(ImageTag.image_id.in_([image.id for image in target_images] or [-1])))).scalars():
        existing_image_tags[row.image_id].add(row.tag_id)
    existing_favorites = {
        (row.user_id, row.image_id)
        for row in (
            await db.execute(select(UserImageFavorite).where(UserImageFavorite.image_id.in_([image.id for image in target_images] or [-1])))
        ).scalars()
    }
    relationship_pairs = {
        (row.sha_a, row.sha_b)
        for row in (
            await db.execute(
                select(BlobRelationship).where(
                    BlobRelationship.sha_a.in_(list(target_by_sha) or [""])
                    | BlobRelationship.sha_b.in_(list(target_by_sha) or [""])
                )
            )
        ).scalars()
    }

    for source in sources:
        source_images = (
            (
                await db.execute(
                    select(Image).where(Image.gallery_id == source.id).order_by(Image.page_num, Image.id)
                )
            )
            .scalars()
            .all()
        )
        source_ids = [image.id for image in source_images]
        tags_by_image: dict[int, list[ImageTag]] = defaultdict(list)
        for tag in (
            await db.execute(select(ImageTag).where(ImageTag.image_id.in_(source_ids or [-1])))
        ).scalars():
            tags_by_image[tag.image_id].append(tag)
        favorites_by_image: dict[int, list[UserImageFavorite]] = defaultdict(list)
        for favorite in (
            await db.execute(select(UserImageFavorite).where(UserImageFavorite.image_id.in_(source_ids or [-1])))
        ).scalars():
            favorites_by_image[favorite.image_id].append(favorite)
        source_blobs = {
            blob.sha256: blob
            for blob in (
                await db.execute(select(Blob).where(Blob.sha256.in_([image.blob_sha256 for image in source_images] or [""])))
            ).scalars()
        }

        for source_image in source_images:
            if source_image.replaced_by_image_id is not None:
                source_replacements[source_image.id] = source_image.replaced_by_image_id
            target_image = target_by_sha.get(source_image.blob_sha256)
            if target_image is None:
                source_blob = source_blobs[source_image.blob_sha256]
                image_is_similar = False
                for target_sha, target_blob in target_blobs.items():
                    if source_blob.phash_int is None or target_blob.phash_int is None:
                        continue
                    distance = _hamming_distance(source_blob.phash_int, target_blob.phash_int)
                    if distance > SIMILAR_PHASH_DISTANCE:
                        continue
                    image_is_similar = True
                    sha_a, sha_b = sorted((source_blob.sha256, target_sha))
                    if (sha_a, sha_b) not in relationship_pairs:
                        db.add(
                            BlobRelationship(
                                sha_a=sha_a,
                                sha_b=sha_b,
                                hamming_dist=distance,
                                relationship="needs_t2",
                                reason="workbench_merge",
                                tier=2,
                            )
                        )
                        relationship_pairs.add((sha_a, sha_b))

                if image_is_similar:
                    similar_count += 1

                mapped_source_item = source_item_map.get(source_image.source_item_row_id or -1)
                mapped_source_item_id = mapped_source_item[0] if mapped_source_item else None
                mapped_source_item_key = mapped_source_item[1] if mapped_source_item else source_image.source_item_id
                copied = Image(
                    gallery_id=target.id,
                    page_num=next_page,
                    filename=source_image.filename,
                    blob_sha256=source_image.blob_sha256,
                    tags_array=list(source_image.tags_array or []),
                    added_at=source_image.added_at,
                    visibility=source_image.visibility,
                    source_item_id=mapped_source_item_key,
                    source_item_url=source_image.source_item_url,
                    source_position=source_image.source_position,
                    source_seen_at=source_image.source_seen_at,
                    hidden_at=source_image.hidden_at,
                    source_item_row_id=mapped_source_item_id,
                )
                db.add(copied)
                await db.flush()
                await increment_ref_count(source_image.blob_sha256, db)
                target_image = copied
                target_by_sha[copied.blob_sha256] = copied
                target_blobs[copied.blob_sha256] = source_blob
                next_page += 1
                copied_count += 1
                copied_source_ids.add(source_image.id)
            else:
                exact_count += 1

            image_map[source_image.id] = target_image.id
            for tag in tags_by_image[source_image.id]:
                if tag.tag_id not in existing_image_tags[target_image.id]:
                    db.add(ImageTag(image_id=target_image.id, tag_id=tag.tag_id, confidence=tag.confidence))
                    existing_image_tags[target_image.id].add(tag.tag_id)
            for favorite in favorites_by_image[source_image.id]:
                key = (favorite.user_id, target_image.id)
                if key not in existing_favorites:
                    db.add(UserImageFavorite(user_id=favorite.user_id, image_id=target_image.id))
                    existing_favorites.add(key)

    for source_image_id in copied_source_ids:
        replaced_by_source_id = source_replacements.get(source_image_id)
        if replaced_by_source_id is None:
            continue
        mapped_replacement = image_map.get(replaced_by_source_id)
        if mapped_replacement is None:
            continue
        copied_image = await db.get(Image, image_map[source_image_id])
        if copied_image is not None:
            copied_image.replaced_by_image_id = mapped_replacement

    return image_map, copied_count, exact_count, similar_count


async def _merge_gallery_relations(db: AsyncSession, target: Gallery, sources: Sequence[Gallery]) -> None:
    source_ids = [source.id for source in sources]
    all_ids = [target.id, *source_ids]

    tag_precedence = {"ai": 0, "metadata": 1, "manual": 2}
    target_tags = {
        row.tag_id: row
        for row in (await db.execute(select(GalleryTag).where(GalleryTag.gallery_id == target.id))).scalars()
    }
    for row in (await db.execute(select(GalleryTag).where(GalleryTag.gallery_id.in_(source_ids)))).scalars():
        existing = target_tags.get(row.tag_id)
        if existing is None:
            existing = GalleryTag(
                gallery_id=target.id,
                tag_id=row.tag_id,
                confidence=row.confidence,
                source=row.source,
            )
            db.add(existing)
            target_tags[row.tag_id] = existing
        else:
            existing.confidence = max(existing.confidence or 0, row.confidence or 0)
            if tag_precedence.get(row.source, 0) > tag_precedence.get(existing.source, 0):
                existing.source = row.source

    target.tags_array = list(
        dict.fromkeys(
            tag
            for gallery in [target, *sources]
            for tag in (gallery.tags_array or [])
        )
    )

    memberships = (
        (await db.execute(select(CollectionGallery).where(CollectionGallery.gallery_id.in_(all_ids))))
        .scalars()
        .all()
    )
    collection_covers = (
        (await db.execute(select(Collection).where(Collection.cover_gallery_id.in_(source_ids))))
        .scalars()
        .all()
    )
    for collection in collection_covers:
        collection.cover_gallery_id = target.id
    target_collections = {row.collection_id for row in memberships if row.gallery_id == target.id}
    max_positions: dict[int, int] = {}
    for row in memberships:
        if row.collection_id in target_collections or row.gallery_id == target.id:
            continue
        if row.collection_id not in max_positions:
            max_positions[row.collection_id] = (
                await db.execute(
                    select(func.coalesce(func.max(CollectionGallery.position), -1)).where(
                        CollectionGallery.collection_id == row.collection_id
                    )
                )
            ).scalar_one()
        max_positions[row.collection_id] += 1
        db.add(CollectionGallery(collection_id=row.collection_id, gallery_id=target.id, position=max_positions[row.collection_id]))
        target_collections.add(row.collection_id)

    for model in (UserFavorite, UserReadingList):
        rows = (await db.execute(select(model).where(model.gallery_id.in_(all_ids)))).scalars().all()
        target_users = {row.user_id for row in rows if row.gallery_id == target.id}
        for row in rows:
            if row.gallery_id != target.id and row.user_id not in target_users:
                db.add(model(user_id=row.user_id, gallery_id=target.id))
                target_users.add(row.user_id)

    ratings = (await db.execute(select(UserRating).where(UserRating.gallery_id.in_(all_ids)))).scalars().all()
    target_rating_users = {row.user_id for row in ratings if row.gallery_id == target.id}
    newest_rating: dict[int, UserRating] = {}
    for row in ratings:
        if row.gallery_id == target.id or row.user_id in target_rating_users:
            continue
        current = newest_rating.get(row.user_id)
        if current is None or (row.rated_at or datetime.min.replace(tzinfo=UTC)) > (
            current.rated_at or datetime.min.replace(tzinfo=UTC)
        ):
            newest_rating[row.user_id] = row
    for row in newest_rating.values():
        db.add(UserRating(user_id=row.user_id, gallery_id=target.id, rating=row.rating, rated_at=row.rated_at))

    excluded = (await db.execute(select(ExcludedBlob).where(ExcludedBlob.gallery_id.in_(all_ids)))).scalars().all()
    target_excluded = {row.blob_sha256 for row in excluded if row.gallery_id == target.id}
    for row in excluded:
        if row.gallery_id != target.id and row.blob_sha256 not in target_excluded:
            db.add(ExcludedBlob(gallery_id=target.id, blob_sha256=row.blob_sha256))
            target_excluded.add(row.blob_sha256)


async def _merge_read_progress(
    db: AsyncSession,
    target_id: int,
    source_ids: Sequence[int],
    image_map: Mapping[int, int],
) -> None:
    rows = (
        (await db.execute(select(ReadProgress).where(ReadProgress.gallery_id.in_([target_id, *source_ids]))))
        .scalars()
        .all()
    )
    target_users = {row.user_id for row in rows if row.gallery_id == target_id}
    newest: dict[int, ReadProgress] = {}
    for row in rows:
        if row.gallery_id == target_id or row.user_id in target_users:
            continue
        current = newest.get(row.user_id)
        if current is None or row.last_read_at > current.last_read_at:
            newest[row.user_id] = row
    for row in newest.values():
        mapped_image_id = image_map.get(row.last_image_id) if row.last_image_id is not None else None
        mapped_page = row.last_page
        if mapped_image_id is not None:
            mapped_page = (
                await db.execute(select(Image.page_num).where(Image.id == mapped_image_id))
            ).scalar_one()
        db.add(
            ReadProgress(
                user_id=row.user_id,
                gallery_id=target_id,
                last_page=mapped_page,
                last_image_id=mapped_image_id,
                last_read_at=row.last_read_at,
            )
        )


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
    for source in sources:
        source.deleted_at = now

    return {
        "target_id": target.id,
        "source_ids": [source.id for source in sources],
        "images_added": copied,
        "exact_sha_skipped": exact,
        "similar_kept_for_review": similar,
        "source_routes": "404",
    }
