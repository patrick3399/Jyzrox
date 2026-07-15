"""Persistent image datasets for AI training and export workflows."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    Blob,
    Collection,
    CollectionGallery,
    Dataset,
    DatasetImage,
    Gallery,
    GalleryTag,
    Image,
    Tag,
)
from services.cas import thumb_url

router = APIRouter(tags=["datasets"])
_member = require_role("member")


class DatasetSelection(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    collection_ids: list[int] = Field(default_factory=list, max_length=100)
    image_ids: list[int] = Field(default_factory=list, max_length=2000)
    tag_query: str | None = Field(default=None, max_length=500)
    tag_query_limit: int = Field(default=5000, ge=1, le=5000)

    @field_validator("tag_query")
    @classmethod
    def validate_tag_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DatasetCreate(DatasetSelection):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


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
            row.updated_at = now
            added += 1
        elif row.source != source:
            row.source = source
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
        .where(Image.visibility == "active", gallery_access_filter(auth))
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


async def _counts(db: AsyncSession, dataset_id: int, auth: dict) -> tuple[int, int, int]:
    rows = (
        await db.execute(
            select(DatasetImage.state, Image.gallery_id)
            .join(Image, Image.id == DatasetImage.image_id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .where(
                DatasetImage.dataset_id == dataset_id,
                Image.visibility == "active",
                gallery_access_filter(auth),
            )
        )
    ).all()
    included = [row for row in rows if row.state == "included"]
    return len(included), len({row.gallery_id for row in included}), len(rows) - len(included)


def _serialize_dataset(dataset: Dataset, member_count: int, gallery_count: int, excluded_count: int) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "selection_spec": dataset.selection_spec or {},
        "member_count": member_count,
        "gallery_count": gallery_count,
        "excluded_count": excluded_count,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


@router.get("/")
async def list_datasets(
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    datasets = (
        (
            await db.execute(
                select(Dataset)
                .where(Dataset.user_id == auth["user_id"])
                .order_by(Dataset.updated_at.desc(), Dataset.id.desc())
            )
        )
        .scalars()
        .all()
    )
    result = []
    for dataset in datasets:
        result.append(_serialize_dataset(dataset, *(await _counts(db, dataset.id, auth))))
    return {"datasets": result}


@router.post("/", status_code=201)
async def create_dataset(
    body: DatasetCreate,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = Dataset(
        user_id=auth["user_id"],
        name=body.name.strip(),
        description=body.description,
        selection_spec={},
    )
    db.add(dataset)
    await db.flush()
    selection_result = await _apply_selection(db, dataset, auth, body)
    await db.commit()
    await db.refresh(dataset)
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset.id,
        action="created",
        added=selection_result["added"],
    )
    counts = await _counts(db, dataset.id, auth)
    return {**_serialize_dataset(dataset, *counts), **selection_result}


@router.get("/{dataset_id}")
async def get_dataset(
    dataset_id: int,
    state: Literal["included", "excluded"] = "included",
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    base_filters = (
        DatasetImage.dataset_id == dataset_id,
        DatasetImage.state == state,
        Image.visibility == "active",
        gallery_access_filter(auth),
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(DatasetImage)
            .join(Image, Image.id == DatasetImage.image_id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .where(*base_filters)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(DatasetImage, Image, Gallery, Blob)
            .join(Image, Image.id == DatasetImage.image_id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(*base_filters)
            .order_by(Gallery.id, Image.page_num, Image.id)
            .offset(page * limit)
            .limit(limit)
        )
    ).all()
    images = [
        {
            "id": image.id,
            "gallery_id": image.gallery_id,
            "gallery_title": gallery.title,
            "page_num": image.page_num,
            "filename": image.filename,
            "width": blob.width,
            "height": blob.height,
            "thumb_url": thumb_url(blob.sha256),
            "state": member.state,
            "source": member.source,
        }
        for member, image, gallery, blob in rows
    ]
    counts = await _counts(db, dataset.id, auth)
    return {
        **_serialize_dataset(dataset, *counts),
        "images": images,
        "state": state,
        "page": page,
        "has_next": (page + 1) * limit < total,
        "total": total,
    }


@router.patch("/{dataset_id}")
async def update_dataset(
    dataset_id: int,
    body: DatasetPatch,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    if body.name is not None:
        dataset.name = body.name.strip()
    if "description" in body.model_fields_set:
        dataset.description = body.description
    dataset.updated_at = datetime.now(UTC)
    await db.commit()
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset_id,
        action="updated",
    )
    return {"status": "ok"}


@router.post("/{dataset_id}/members")
async def add_dataset_members(
    dataset_id: int,
    body: DatasetSelection,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    result = await _apply_selection(db, dataset, auth, body)
    await db.commit()
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset_id,
        action="members_added",
        added=result["added"],
    )
    return {"status": "ok", **result}


@router.delete("/{dataset_id}/images/{image_id}")
async def exclude_dataset_image(
    dataset_id: int,
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    member = (
        await db.execute(
            select(DatasetImage).where(
                DatasetImage.dataset_id == dataset_id,
                DatasetImage.image_id == image_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Image is not in dataset")
    member.state = "excluded"
    member.updated_at = datetime.now(UTC)
    dataset.updated_at = datetime.now(UTC)
    await db.commit()
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset_id,
        action="image_excluded",
        image_id=image_id,
    )
    return {"status": "ok", "state": "excluded"}


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    await db.delete(dataset)
    await db.commit()
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset_id,
        action="deleted",
    )
    return {"status": "ok"}
