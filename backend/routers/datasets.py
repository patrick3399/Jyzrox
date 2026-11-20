"""Persistent image datasets for AI training and export workflows."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    Blob,
    Dataset,
    DatasetImage,
    Gallery,
    Image,
)
from routers.datasets_ops import router as _ops_router
from services.cas import thumb_srcset, thumb_url
from services.dataset_filters import _counts, _serialize_dataset
from services.dataset_schemas import DatasetCreate, DatasetPatch
from services.dataset_selection import _apply_selection, _owned_dataset

router = APIRouter(tags=["datasets"])
_member = require_role("member")


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
        Image.blob_sha256.is_not(None),
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
            "thumb_srcset": thumb_srcset(blob.sha256),
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


router.include_router(_ops_router)
