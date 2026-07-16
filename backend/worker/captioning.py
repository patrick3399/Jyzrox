"""Natural-language dataset caption generation jobs."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import Dataset, DatasetImage, Image, ImageTag, Tag
from services.caption_engine import caption_engine_registry
from services.cas import resolve_blob_path
from services.settings_store import get_toggle
from worker.constants import _IMAGE_EXTS, logger


async def caption_job(ctx: dict, dataset_id: int, engine_id: str, actor_user_id: int | None = None) -> dict:
    """Generate captions for every included image in a dataset."""
    if not await get_toggle("setting:captioner_enabled", settings.captioner_enabled):
        return {"status": "skipped", "reason": "captioner_enabled=false"}
    engine = caption_engine_registry.get(engine_id)
    if engine is None:
        raise ValueError(f"Unknown caption engine: {engine_id}")
    health = await engine.health()
    if not health.get("online"):
        raise RuntimeError(f"Caption engine is offline: {health.get('error', engine_id)}")

    async with AsyncSessionLocal() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            raise ValueError("Dataset not found")
        images = (
            (
                await session.execute(
                    select(Image)
                    .join(DatasetImage, DatasetImage.image_id == Image.id)
                    .where(
                        DatasetImage.dataset_id == dataset_id,
                        DatasetImage.state == "included",
                        Image.visibility == "active",
                    )
                    .options(selectinload(Image.blob))
                    .order_by(Image.id)
                )
            )
            .scalars()
            .all()
        )
        confidence_rows = (
            await session.execute(
                select(ImageTag.image_id, Tag.namespace, Tag.name, ImageTag.confidence)
                .join(Tag, Tag.id == ImageTag.tag_id)
                .where(ImageTag.image_id.in_([image.id for image in images]))
            )
        ).all() if images else []
        confidence: dict[int, dict[str, float | None]] = {}
        for image_id, namespace, name, value in confidence_rows:
            confidence.setdefault(image_id, {})[f"{namespace}:{name}"] = value

        generated = 0
        failed = 0
        for image in images:
            source = resolve_blob_path(image.blob)
            if not source.is_file() or source.suffix.lower() not in _IMAGE_EXTS:
                failed += 1
                continue
            values = confidence.get(image.id, {})
            tags = sorted(
                tag
                for tag in (image.tags_array or [])
                if values.get(tag) is None or values[tag] >= dataset.tag_threshold
            )
            try:
                result = await engine.caption(source, tags)
            except Exception as exc:
                logger.warning("[caption] image %d failed: %s", image.id, exc)
                failed += 1
                continue
            image.caption = result.caption
            generated += 1
        await session.commit()

    await emit_safe(
        EventType.DATASET_UPDATED,
        actor_user_id=actor_user_id,
        resource_type="dataset",
        resource_id=dataset_id,
        action="captions_generated",
        engine=engine_id,
        generated=generated,
        failed=failed,
    )
    return {"status": "done", "generated": generated, "failed": failed, "engine": engine_id}
