"""Persistent image datasets for AI training and export workflows."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
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
from services.caption_engine import caption_engine_registry
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
    tag_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


class DatasetFilterConfig(BaseModel):
    min_width: int | None = Field(default=None, ge=1, le=100000)
    min_height: int | None = Field(default=None, ge=1, le=100000)
    max_aspect_ratio: float | None = Field(default=None, gt=1.0, le=100.0)
    phash_distance: int | None = Field(default=None, ge=0, le=64)


class ImageCaptionPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=10000)

    @field_validator("caption")
    @classmethod
    def normalize_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CaptionBatchRequest(BaseModel):
    operation: Literal["prepend_trigger", "search_replace"]
    trigger_word: str | None = Field(default=None, max_length=200)
    search: str | None = Field(default=None, max_length=1000)
    replacement: str = Field(default="", max_length=1000)


class CaptionGenerateRequest(BaseModel):
    engine: Literal["florence2", "joycaption"] = "florence2"


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
        "tag_threshold": dataset.tag_threshold,
        "selection_spec": dataset.selection_spec or {},
        "member_count": member_count,
        "gallery_count": gallery_count,
        "excluded_count": excluded_count,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


_AUTO_EXCLUSION_REASONS = frozenset({"min_resolution", "aspect_ratio", "phash_duplicate"})


async def _dataset_filter_rows(db: AsyncSession, dataset_id: int, auth: dict) -> list:
    return list(
        (
            await db.execute(
                select(DatasetImage, Blob)
                .join(Image, Image.id == DatasetImage.image_id)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .join(Blob, Blob.sha256 == Image.blob_sha256)
                .where(
                    DatasetImage.dataset_id == dataset_id,
                    Image.visibility == "active",
                    gallery_access_filter(auth),
                )
                .order_by(Image.id)
            )
        ).all()
    )


def _filter_reason(blob: Blob, config: DatasetFilterConfig) -> tuple[str | None, bool]:
    width = blob.width
    height = blob.height
    if config.min_width is None and config.min_height is None and config.max_aspect_ratio is None:
        return None, False
    if config.min_width is not None and width is None:
        return None, True
    if config.min_height is not None and height is None:
        return None, True
    if (config.min_width is not None and width is not None and width < config.min_width) or (
        config.min_height is not None and height is not None and height < config.min_height
    ):
        return "min_resolution", False
    if config.max_aspect_ratio is not None:
        if width is None or height is None or width <= 0 or height <= 0:
            return None, True
        aspect_ratio = max(width / height, height / width)
        if aspect_ratio > config.max_aspect_ratio:
            return "aspect_ratio", False
    return None, False


def _phash_distance(left: int, right: int) -> int:
    mask = (1 << 64) - 1
    return ((left & mask) ^ (right & mask)).bit_count()


def _evaluate_filters(rows: list, config: DatasetFilterConfig) -> tuple[list[tuple[DatasetImage, str | None]], dict]:
    decisions: list[tuple[DatasetImage, str | None]] = []
    reason_counts = {"min_resolution": 0, "aspect_ratio": 0, "phash_duplicate": 0}
    manual_excluded = 0
    unknown_dimensions = 0
    unknown_phash = 0
    newly_excluded = 0
    would_restore = 0

    retained_phashes: list[int] = []
    for member, blob in rows:
        is_auto_excluded = member.exclusion_reason in _AUTO_EXCLUSION_REASONS
        if member.state == "excluded" and not is_auto_excluded:
            manual_excluded += 1
            continue
        reason, dimensions_unknown = _filter_reason(blob, config)
        if dimensions_unknown:
            unknown_dimensions += 1
        if reason is None and config.phash_distance is not None:
            if blob.phash_int is None:
                unknown_phash += 1
            elif any(_phash_distance(blob.phash_int, previous) <= config.phash_distance for previous in retained_phashes):
                reason = "phash_duplicate"
            else:
                retained_phashes.append(blob.phash_int)
        if reason is not None:
            reason_counts[reason] += 1
            if member.state == "included":
                newly_excluded += 1
        elif is_auto_excluded:
            would_restore += 1
        decisions.append((member, reason))

    auto_excluded = sum(reason_counts.values())
    return decisions, {
        "total": len(rows),
        "auto_excluded": auto_excluded,
        "newly_excluded": newly_excluded,
        "would_restore": would_restore,
        "manual_excluded": manual_excluded,
        "remaining": len(rows) - manual_excluded - auto_excluded,
        "unknown_dimensions": unknown_dimensions,
        "unknown_phash": unknown_phash,
        "reasons": reason_counts,
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
            "caption": image.caption,
            "thumb_url": thumb_url(blob.sha256),
            "state": member.state,
            "source": member.source,
            "exclusion_reason": member.exclusion_reason,
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
    if body.tag_threshold is not None:
        dataset.tag_threshold = body.tag_threshold
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


@router.patch("/{dataset_id}/images/{image_id}/caption")
async def update_image_caption(
    dataset_id: int,
    image_id: int,
    body: ImageCaptionPatch,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    await _owned_dataset(db, dataset_id, auth["user_id"])
    image = (
        await db.execute(
            select(Image)
            .join(DatasetImage, DatasetImage.image_id == Image.id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .where(
                DatasetImage.dataset_id == dataset_id,
                Image.id == image_id,
                Image.visibility == "active",
                gallery_access_filter(auth),
            )
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Dataset image not found")
    image.caption = body.caption
    await db.commit()
    return {"status": "ok", "caption": image.caption}


@router.post("/{dataset_id}/captions/batch")
async def batch_update_captions(
    dataset_id: int,
    body: CaptionBatchRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    await _owned_dataset(db, dataset_id, auth["user_id"])
    images = (
        (
            await db.execute(
                select(Image)
                .join(DatasetImage, DatasetImage.image_id == Image.id)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .where(
                    DatasetImage.dataset_id == dataset_id,
                    DatasetImage.state == "included",
                    Image.visibility == "active",
                    gallery_access_filter(auth),
                )
            )
        )
        .scalars()
        .all()
    )
    changed = 0
    if body.operation == "prepend_trigger":
        trigger = (body.trigger_word or "").strip()
        if not trigger:
            raise HTTPException(status_code=400, detail="trigger_word is required")
        for image in images:
            current = (image.caption or "").strip()
            if current != trigger and not current.startswith(f"{trigger},"):
                image.caption = f"{trigger}, {current}" if current else trigger
                changed += 1
    else:
        search = body.search or ""
        if not search:
            raise HTTPException(status_code=400, detail="search is required")
        for image in images:
            current = image.caption or ""
            updated = current.replace(search, body.replacement)
            if updated != current:
                image.caption = updated.strip() or None
                changed += 1
    await db.commit()
    return {"status": "ok", "changed": changed}


@router.post("/{dataset_id}/captions/generate", status_code=202)
async def generate_dataset_captions(
    dataset_id: int,
    body: CaptionGenerateRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    await _owned_dataset(db, dataset_id, auth["user_id"])
    if caption_engine_registry.get(body.engine) is None:
        raise HTTPException(status_code=400, detail="Unknown caption engine")
    job = await core.queue.enqueue(
        "caption_job",
        dataset_id=dataset_id,
        engine_id=body.engine,
        actor_user_id=auth["user_id"],
        _timeout=7200,
    )
    return {"status": "queued", "job_id": job.key, "engine": body.engine}


@router.post("/{dataset_id}/filters/preview")
async def preview_dataset_filters(
    dataset_id: int,
    body: DatasetFilterConfig,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    await _owned_dataset(db, dataset_id, auth["user_id"])
    _, report = _evaluate_filters(await _dataset_filter_rows(db, dataset_id, auth), body)
    return {"status": "ok", "filters": body.model_dump(), **report}


@router.post("/{dataset_id}/filters/apply")
async def apply_dataset_filters(
    dataset_id: int,
    body: DatasetFilterConfig,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _owned_dataset(db, dataset_id, auth["user_id"])
    decisions, report = _evaluate_filters(await _dataset_filter_rows(db, dataset_id, auth), body)
    now = datetime.now(UTC)
    changed = 0
    for member, reason in decisions:
        next_state = "excluded" if reason is not None else "included"
        if member.state != next_state or member.exclusion_reason != reason:
            member.state = next_state
            member.exclusion_reason = reason
            member.updated_at = now
            changed += 1
    spec = dict(dataset.selection_spec or {})
    spec["filters"] = body.model_dump()
    dataset.selection_spec = spec
    dataset.updated_at = now
    await db.commit()
    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="dataset",
        resource_id=dataset_id,
        action="filters_applied",
        changed=changed,
        auto_excluded=report["auto_excluded"],
    )
    return {"status": "ok", "filters": body.model_dump(), "changed": changed, **report}


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
    member.exclusion_reason = "manual"
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
