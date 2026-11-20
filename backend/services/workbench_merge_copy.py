"""Source-item and image copy steps of the Library Workbench gallery merge."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Blob, BlobRelationship, Gallery, GallerySourceItem, Image, UserImageFavorite
from services.cas import increment_ref_count

SIMILAR_PHASH_DISTANCE = 6


def _hamming_distance(left: int, right: int) -> int:
    mask = (1 << 64) - 1
    return ((left & mask) ^ (right & mask)).bit_count()


async def _copy_source_items(
    db: AsyncSession,
    target_id: int,
    sources: Sequence[Gallery],
) -> dict[int, tuple[int, str]]:
    existing = (
        (await db.execute(select(GallerySourceItem).where(GallerySourceItem.gallery_id == target_id))).scalars().all()
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
            (await db.execute(select(Blob).where(Blob.sha256.in_(list(target_by_sha) or [""])))).scalars().all()
        )
    }
    next_page = max((image.page_num for image in target_images), default=0) + 1
    image_map: dict[int, int] = {}
    copied_source_ids: set[int] = set()
    source_replacements: dict[int, int] = {}
    copied_count = 0
    exact_count = 0
    similar_count = 0

    existing_favorites = {
        (row.user_id, row.image_id)
        for row in (
            await db.execute(
                select(UserImageFavorite).where(
                    UserImageFavorite.image_id.in_([image.id for image in target_images] or [-1])
                )
            )
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
            (await db.execute(select(Image).where(Image.gallery_id == source.id).order_by(Image.page_num, Image.id)))
            .scalars()
            .all()
        )
        source_ids = [image.id for image in source_images]
        favorites_by_image: dict[int, list[UserImageFavorite]] = defaultdict(list)
        for favorite in (
            await db.execute(select(UserImageFavorite).where(UserImageFavorite.image_id.in_(source_ids or [-1])))
        ).scalars():
            favorites_by_image[favorite.image_id].append(favorite)
        source_blobs = {
            blob.sha256: blob
            for blob in (
                await db.execute(
                    select(Blob).where(Blob.sha256.in_([image.blob_sha256 for image in source_images] or [""]))
                )
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
                    external_path=source_image.external_path,
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
