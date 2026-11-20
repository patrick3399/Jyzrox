"""Relation and read-progress merge steps of the Library Workbench gallery merge."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Collection,
    CollectionGallery,
    ExcludedBlob,
    Gallery,
    GalleryTag,
    Image,
    ReadProgress,
    UserFavorite,
    UserRating,
    UserReadingList,
)


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

    target.tags_array = list(dict.fromkeys(tag for gallery in [target, *sources] for tag in (gallery.tags_array or [])))

    memberships = (
        (await db.execute(select(CollectionGallery).where(CollectionGallery.gallery_id.in_(all_ids)))).scalars().all()
    )
    collection_covers = (
        (await db.execute(select(Collection).where(Collection.cover_gallery_id.in_(source_ids)))).scalars().all()
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
        db.add(
            CollectionGallery(
                collection_id=row.collection_id, gallery_id=target.id, position=max_positions[row.collection_id]
            )
        )
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
            mapped_page = (await db.execute(select(Image.page_num).where(Image.id == mapped_image_id))).scalar_one()
        db.add(
            ReadProgress(
                user_id=row.user_id,
                gallery_id=target_id,
                last_page=mapped_page,
                last_image_id=mapped_image_id,
                last_read_at=row.last_read_at,
            )
        )
