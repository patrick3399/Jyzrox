"""Image processing enqueue API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.auth import gallery_access_filter, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import Gallery, Image
from plugins.registry import plugin_registry

router = APIRouter(tags=["processing"])
_member = require_role("member")


class ProcessImageRequest(BaseModel):
    processor_id: str = Field(default="swarmui", min_length=1, max_length=80)
    model: str = Field(default="", max_length=300)
    scale: float = Field(default=2, ge=1.5, le=4)
    tiling: bool = True


@router.post("/images/{image_id}", status_code=202)
async def enqueue_image_process(
    image_id: int,
    req: ProcessImageRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Queue processing for an accessible active image."""
    image = (
        await db.execute(
            select(Image.id)
            .join(Gallery, Image.gallery_id == Gallery.id)
            .where(Image.id == image_id, Image.visibility == "active", gallery_access_filter(auth))
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    if plugin_registry.get_processor(req.processor_id) is None:
        raise HTTPException(status_code=400, detail="Unknown image processor")

    job = await core.queue.enqueue(
        "process_job",
        image_id=image_id,
        processor_id=req.processor_id,
        options=req.model_dump(exclude={"processor_id"}),
        actor_user_id=auth["user_id"],
        _timeout=1800,
    )
    await emit_safe(
        EventType.IMAGE_PROCESS_ENQUEUED,
        actor_user_id=auth["user_id"],
        resource_type="image",
        resource_id=image_id,
        processor=req.processor_id,
        job_id=job.key,
    )
    return {"status": "queued", "job_id": job.key, "image_id": image_id}
