"""General image processing job backed by Processable plugins."""

import asyncio
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import Gallery, Image
from plugins.registry import plugin_registry
from services.cas import create_library_symlink, increment_ref_count, resolve_blob_path, store_blob
from worker.helpers import _sha256

logger = logging.getLogger(__name__)


def _inspect_image(path: Path) -> tuple[int, int]:
    with PILImage.open(path) as image:
        image.verify()
    with PILImage.open(path) as image:
        return image.size


async def process_job(
    ctx: dict,
    image_id: int,
    processor_id: str,
    options: dict,
    actor_user_id: int | None = None,
) -> dict:
    """Process one active image and replace it while retaining the prior Image row."""
    processor = plugin_registry.get_processor(processor_id)
    if processor is None:
        raise ValueError(f"Unknown image processor: {processor_id}")

    async with AsyncSessionLocal() as session:
        original = (
            await session.execute(
                select(Image)
                .where(Image.id == image_id, Image.visibility == "active")
                .options(selectinload(Image.blob))
            )
        ).scalar_one_or_none()
        if original is None:
            raise ValueError("Image is no longer active")
        original_sha256 = original.blob_sha256
        input_path = resolve_blob_path(original.blob, original.external_path)

    if not input_path.is_file():
        raise FileNotFoundError(f"Image blob is missing: {original_sha256}")

    await emit_safe(
        EventType.IMAGE_PROCESS_STARTED,
        actor_user_id=actor_user_id,
        resource_type="image",
        resource_id=image_id,
        processor=processor_id,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="jyzrox-process-") as temp_dir:
            result = await processor.process(input_path, Path(temp_dir), options)
            if result.status != "done" or not result.output_path:
                raise RuntimeError(result.error or "Image processor failed")
            output_path = Path(result.output_path)
            if not output_path.is_file():
                raise RuntimeError("Image processor did not create its declared output")

            width, height = await asyncio.to_thread(_inspect_image, output_path)
            output_sha256 = await asyncio.to_thread(_sha256, output_path)
            if output_sha256 == original_sha256:
                return {"status": "unchanged", "image_id": image_id, "sha256": original_sha256}

            async with AsyncSessionLocal() as session:
                new_image_id = await _replace_processed_image(
                    session,
                    image_id=image_id,
                    expected_sha256=original_sha256,
                    output_path=output_path,
                    output_sha256=output_sha256,
                    width=width,
                    height=height,
                )

        await emit_safe(
            EventType.IMAGE_PROCESS_COMPLETED,
            actor_user_id=actor_user_id,
            resource_type="image",
            resource_id=new_image_id,
            processor=processor_id,
            original_image_id=image_id,
            width=width,
            height=height,
        )
        return {
            "status": "done",
            "image_id": new_image_id,
            "original_image_id": image_id,
            "sha256": output_sha256,
            "width": width,
            "height": height,
        }
    except Exception as exc:
        logger.exception("Image processing failed for image %s", image_id)
        await emit_safe(
            EventType.IMAGE_PROCESS_FAILED,
            actor_user_id=actor_user_id,
            resource_type="image",
            resource_id=image_id,
            processor=processor_id,
            error=str(exc),
        )
        raise


async def _replace_processed_image(
    session,
    *,
    image_id: int,
    expected_sha256: str,
    output_path: Path,
    output_sha256: str,
    width: int,
    height: int,
) -> int:
    """Atomically switch the active Image row while retaining its predecessor."""
    current = (
        await session.execute(
            select(Image)
            .where(Image.id == image_id, Image.visibility == "active")
            .options(selectinload(Image.blob))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if current is None or current.blob_sha256 != expected_sha256:
        raise RuntimeError("Image changed while processing; output was not applied")
    gallery = await session.get(Gallery, current.gallery_id)
    if gallery is None:
        raise RuntimeError("Gallery no longer exists")

    blob = await store_blob(output_path, output_sha256, session)
    blob.width = width
    blob.height = height
    await session.flush()

    page_num = current.page_num
    current.visibility = "replaced"
    current.page_num = -current.id
    replacement = Image(
        gallery_id=current.gallery_id,
        page_num=page_num,
        filename=current.filename,
        blob_sha256=output_sha256,
        tags_array=list(current.tags_array or []),
        added_at=datetime.now(UTC),
        visibility="active",
        source_item_id=current.source_item_id,
        source_item_url=current.source_item_url,
        source_position=current.source_position,
        source_seen_at=current.source_seen_at,
        source_item_row_id=current.source_item_row_id,
    )
    session.add(replacement)
    await session.flush()
    current.replaced_by_image_id = replacement.id
    await increment_ref_count(output_sha256, session)
    await session.commit()

    if replacement.filename:
        await create_library_symlink(gallery.source, gallery.source_id, replacement.filename, blob)
    return replacement.id
