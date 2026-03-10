"""AI tagging job for the worker package."""

import asyncio
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import Image, Tag
from services.cas import resolve_blob_path
from worker.constants import _IMAGE_EXTS, logger


async def tag_job(ctx: dict, gallery_id: int) -> dict:
    """AI tagging via WD14 — tags all images in a gallery."""
    if not settings.tag_model_enabled:
        logger.info("[tag] gallery_id=%d skipped (TAG_MODEL_ENABLED=false)", gallery_id)
        return {"status": "skipped", "reason": "TAG_MODEL_ENABLED=false"}

    logger.info("[tag] gallery_id=%d", gallery_id)

    from sqlalchemy.orm import selectinload

    from services.tagger import predict

    tagged = 0
    async with AsyncSessionLocal() as session:
        images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        for img in images:
            blob = img.blob
            if not blob:
                continue
            src = resolve_blob_path(blob)
            if not src.exists() or src.suffix.lower() not in _IMAGE_EXTS:
                continue

            try:
                results = await asyncio.to_thread(
                    predict,
                    str(src),
                    settings.tag_general_threshold,
                    settings.tag_character_threshold,
                )
            except Exception as exc:
                logger.warning("[tag] image %d failed: %s", img.id, exc)
                continue

            if not results:
                continue

            # Build tag strings for tags_array
            tag_strings = [f"{ns}:{name}" for ns, name, _ in results]

            # Upsert tags to tags table and get IDs
            tag_values = [{"namespace": ns, "name": name, "count": 0} for ns, name, _ in results]
            if tag_values:
                tag_stmt = (
                    pg_insert(Tag)
                    .values(tag_values)
                    .on_conflict_do_nothing(index_elements=["namespace", "name"])
                    .returning(Tag.id, Tag.namespace, Tag.name)
                )
                tag_rows = (await session.execute(tag_stmt)).all()

                # For tags that already existed (on_conflict_do_nothing returns nothing for those),
                # we need to fetch their IDs separately
                existing_keys = {(r.namespace, r.name) for r in tag_rows}
                missing = [(ns, name) for ns, name, _ in results if (ns, name) not in existing_keys]

                tag_id_map: dict[tuple[str, str], int] = {(r.namespace, r.name): r.id for r in tag_rows}

                if missing:
                    for ns, name in missing:
                        row = (await session.execute(
                            select(Tag.id).where(Tag.namespace == ns, Tag.name == name)
                        )).scalar_one_or_none()
                        if row:
                            tag_id_map[(ns, name)] = row

                # Build confidence map
                conf_map = {(ns, name): conf for ns, name, conf in results}

                # Upsert image_tags
                from db.models import ImageTag
                it_values = []
                for (ns, name), tid in tag_id_map.items():
                    it_values.append({
                        "image_id": img.id,
                        "tag_id": tid,
                        "confidence": conf_map.get((ns, name)),
                    })

                if it_values:
                    it_stmt = (
                        pg_insert(ImageTag)
                        .values(it_values)
                        .on_conflict_do_update(
                            index_elements=["image_id", "tag_id"],
                            set_={"confidence": pg_insert(ImageTag).excluded.confidence},
                        )
                    )
                    await session.execute(it_stmt)

            # Update image's tags_array (merge with existing)
            existing_tags = set(img.tags_array or [])
            existing_tags.update(tag_strings)
            img.tags_array = list(existing_tags)

            tagged += 1

        await session.commit()

    logger.info("[tag] gallery_id=%d: %d images tagged", gallery_id, tagged)
    return {"status": "done", "tagged": tagged}
