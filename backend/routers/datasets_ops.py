"""Dataset caption, filter, member and delete routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    DatasetImage,
    Gallery,
    Image,
)
from services.dataset_filters import _dataset_filter_rows, _evaluate_filters
from services.dataset_schemas import CaptionBatchRequest, DatasetFilterConfig, DatasetSelection, ImageCaptionPatch
from services.dataset_selection import _apply_selection, _owned_dataset

router = APIRouter()
_member = require_role("member")


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
