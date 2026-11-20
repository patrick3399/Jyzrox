"""Dataset selection helpers."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import (
    Collection,
    CollectionGallery,
    Dataset,
    DatasetImage,
    Gallery,
    GalleryTag,
    Image,
    Tag,
)
from services.dataset_schemas import DatasetSelection


def _unique_ids(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


async def _owned_dataset(db: AsyncSession, dataset_id: int, user_id: int) -> Dataset:
    dataset = (
        await db.execute(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id))
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


async def _visible_image_ids(db: AsyncSession, auth: dict, image_ids: list[int]) -> set[int]:
    if not image_ids:
        return set()
    return set(
        (
            await db.execute(
                select(Image.id)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .where(
                    Image.id.in_(image_ids),
                    Image.visibility == "active",
                    # Datasets hold hashed pages only; a pending page has no blob.
                    Image.blob_sha256.is_not(None),
                    gallery_access_filter(auth),
                )
            )
        )
        .scalars()
        .all()
    )


async def _include_images(
    db: AsyncSession,
    dataset: Dataset,
    auth: dict,
    image_ids: list[int],
    *,
    source: str,
) -> tuple[int, list[int]]:
    requested = _unique_ids(image_ids)
    visible = await _visible_image_ids(db, auth, requested)
    denied = [image_id for image_id in requested if image_id not in visible]
    if not visible:
        return 0, denied

    existing_rows = (
        (
            await db.execute(
                select(DatasetImage).where(
                    DatasetImage.dataset_id == dataset.id,
                    DatasetImage.image_id.in_(visible),
                )
            )
        )
        .scalars()
        .all()
    )
    existing = {row.image_id: row for row in existing_rows}
    now = datetime.now(UTC)
    added = 0
    for image_id in visible:
        row = existing.get(image_id)
        if row is None:
            db.add(DatasetImage(dataset_id=dataset.id, image_id=image_id, state="included", source=source))
            added += 1
        elif row.state != "included":
            row.state = "included"
            row.source = source
            row.exclusion_reason = None
            row.updated_at = now
            added += 1
        elif row.source != source:
            row.source = source
            row.exclusion_reason = None
            row.updated_at = now
    return added, denied


async def _gallery_image_ids(
    db: AsyncSession,
    auth: dict,
    gallery_ids: list[int],
) -> tuple[list[int], list[int]]:
    requested = _unique_ids(gallery_ids)
    if not requested:
        return [], []
    visible_galleries = set(
        (await db.execute(select(Gallery.id).where(Gallery.id.in_(requested), gallery_access_filter(auth))))
        .scalars()
        .all()
    )
    denied = [gallery_id for gallery_id in requested if gallery_id not in visible_galleries]
    if not visible_galleries:
        return [], denied
    image_ids = (
        (
            await db.execute(
                select(Image.id).where(
                    Image.gallery_id.in_(visible_galleries),
                    Image.visibility == "active",
                    Image.blob_sha256.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(image_ids), denied


async def _collection_gallery_ids(
    db: AsyncSession,
    auth: dict,
    collection_ids: list[int],
) -> tuple[list[int], list[int]]:
    requested = _unique_ids(collection_ids)
    if not requested:
        return [], []
    owned = set(
        (
            await db.execute(
                select(Collection.id).where(
                    Collection.id.in_(requested),
                    Collection.user_id == auth["user_id"],
                )
            )
        )
        .scalars()
        .all()
    )
    denied = [collection_id for collection_id in requested if collection_id not in owned]
    if not owned:
        return [], denied
    gallery_ids = (
        (
            await db.execute(
                select(CollectionGallery.gallery_id)
                .join(Gallery, Gallery.id == CollectionGallery.gallery_id)
                .where(
                    CollectionGallery.collection_id.in_(owned),
                    gallery_access_filter(auth),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(dict.fromkeys(gallery_ids)), denied


def _parse_tag_query(value: str) -> tuple[list[str], list[str]]:
    tokens = list(dict.fromkeys(value.split()))[:20]
    included = [token for token in tokens if not token.startswith("-")]
    excluded = [token[1:] for token in tokens if token.startswith("-") and len(token) > 1]
    return included, excluded


async def _tag_query_image_ids(
    db: AsyncSession,
    auth: dict,
    query: str | None,
    limit: int,
) -> tuple[list[int], bool]:
    if not query:
        return [], False
    included, excluded = _parse_tag_query(query)
    if not included and not excluded:
        return [], False
    stmt = (
        select(Image.id)
        .join(Gallery, Gallery.id == Image.gallery_id)
        .where(Image.visibility == "active", Image.blob_sha256.is_not(None), gallery_access_filter(auth))
        .order_by(Image.id)
        .limit(limit + 1)
    )
    for token in included:
        namespace, separator, name = token.partition(":")
        tag_filter = Tag.name == name if separator else Tag.name == namespace
        if separator:
            tag_filter = tag_filter & (Tag.namespace == namespace)
        stmt = stmt.where(
            exists(
                select(GalleryTag.gallery_id)
                .join(Tag, Tag.id == GalleryTag.tag_id)
                .where(GalleryTag.gallery_id == Gallery.id, tag_filter)
            )
        )
    for token in excluded:
        namespace, separator, name = token.partition(":")
        tag_filter = Tag.name == name if separator else Tag.name == namespace
        if separator:
            tag_filter = tag_filter & (Tag.namespace == namespace)
        stmt = stmt.where(
            ~exists(
                select(GalleryTag.gallery_id)
                .join(Tag, Tag.id == GalleryTag.tag_id)
                .where(GalleryTag.gallery_id == Gallery.id, tag_filter)
            )
        )
    image_ids = list((await db.execute(stmt)).scalars().all())
    return image_ids[:limit], len(image_ids) > limit


def _merge_selection_spec(dataset: Dataset, selection: DatasetSelection) -> None:
    spec = dict(dataset.selection_spec or {})
    for key in ("gallery_ids", "collection_ids", "image_ids"):
        incoming = getattr(selection, key)
        if incoming:
            spec[key] = _unique_ids([*(spec.get(key) or []), *incoming])
    if selection.tag_query:
        spec["tag_query"] = selection.tag_query
        spec["tag_query_limit"] = selection.tag_query_limit
    dataset.selection_spec = spec


async def _apply_selection(
    db: AsyncSession,
    dataset: Dataset,
    auth: dict,
    selection: DatasetSelection,
) -> dict:
    gallery_ids = _unique_ids(selection.gallery_ids)
    collection_gallery_ids, denied_collections = await _collection_gallery_ids(db, auth, selection.collection_ids)

    tag_query_images, tag_query_truncated = await _tag_query_image_ids(
        db,
        auth,
        selection.tag_query,
        selection.tag_query_limit,
    )
    tag_query_added, _ = await _include_images(db, dataset, auth, tag_query_images, source="tag_query")
    collection_images, _ = await _gallery_image_ids(db, auth, collection_gallery_ids)
    collection_added, _ = await _include_images(db, dataset, auth, collection_images, source="collection")
    gallery_images, denied_galleries = await _gallery_image_ids(db, auth, gallery_ids)
    gallery_added, _ = await _include_images(db, dataset, auth, gallery_images, source="gallery")
    image_added, denied_images = await _include_images(
        db,
        dataset,
        auth,
        selection.image_ids,
        source="manual",
    )
    _merge_selection_spec(dataset, selection)
    dataset.updated_at = datetime.now(UTC)
    return {
        "added": tag_query_added + collection_added + gallery_added + image_added,
        "tag_query_truncated": tag_query_truncated,
        "denied": {
            "gallery_ids": denied_galleries,
            "collection_ids": denied_collections,
            "image_ids": denied_images,
        },
    }
