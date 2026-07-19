"""AI tagging job for the worker package."""

import httpx
from sqlalchemy import case, func, literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import GalleryTag, Image, ImageTag, Tag
from services.cas import resolve_blob_path
from services.settings_store import get_float_setting, get_toggle
from services.tag_helpers import clear_ai_tags, rebuild_gallery_tags_array
from worker.constants import _IMAGE_EXTS, logger


async def _tagger_available(client: httpx.AsyncClient) -> bool:
    """Check if the tagger microservice is reachable and model is loaded."""
    try:
        resp = await client.get(f"{settings.tagger_url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("model_loaded", False)
    except Exception:
        pass
    return False


async def _predict_remote(
    client: httpx.AsyncClient,
    image_path: str,
    general_threshold: float,
    character_threshold: float,
) -> list[tuple[str, str, float]]:
    """Call the tagger microservice POST /predict endpoint."""
    resp = await client.post(
        f"{settings.tagger_url}/predict",
        json={
            "image_path": image_path,
            "general_threshold": general_threshold,
            "character_threshold": character_threshold,
        },
        timeout=settings.tagger_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return [(t["namespace"], t["name"], t["confidence"]) for t in data["tags"]]


async def _aggregate_to_gallery(session, gallery_id: int, threshold: float) -> int:
    """
    Aggregate image-level AI tags up to gallery_tags.

    For each tag that appears in at least one image of the gallery with
    MAX(confidence) >= threshold, upsert a gallery_tags row with source='ai'.
    Existing 'metadata' or 'manual' source rows are never downgraded.

    Returns the number of tag rows upserted.
    """
    image_subq = select(Image.id).where(Image.gallery_id == gallery_id)

    agg_rows = (
        await session.execute(
            select(
                ImageTag.tag_id,
                func.max(ImageTag.confidence).label("max_conf"),
            )
            .where(ImageTag.image_id.in_(image_subq))
            .group_by(ImageTag.tag_id)
            .having(func.max(ImageTag.confidence) >= threshold)
        )
    ).all()

    if not agg_rows:
        return 0

    gt_values = [
        {
            "gallery_id": gallery_id,
            "tag_id": row.tag_id,
            "confidence": row.max_conf,
            "source": "ai",
        }
        for row in agg_rows
    ]

    stmt = (
        pg_insert(GalleryTag)
        .values(gt_values)
        .on_conflict_do_update(
            index_elements=["gallery_id", "tag_id"],
            set_={
                "confidence": case(
                    (GalleryTag.source.in_(["metadata", "manual"]), GalleryTag.confidence),
                    else_=pg_insert(GalleryTag).excluded.confidence,
                ),
                "source": case(
                    (GalleryTag.source.in_(["metadata", "manual"]), GalleryTag.source),
                    else_=literal("ai"),
                ),
            },
        )
    )
    await session.execute(stmt)
    return len(gt_values)


async def tag_job(ctx: dict, gallery_id: int) -> dict:
    """AI tagging via WD14 — tags all images in a gallery via remote tagger service."""
    # Runtime (Redis) toggle wins; env TAG_MODEL_ENABLED is only the default (AIT-005)
    if not await get_toggle("setting:ai_tagging_enabled", settings.tag_model_enabled):
        logger.info("[tag] gallery_id=%d skipped (ai_tagging_enabled=false)", gallery_id)
        return {"status": "skipped", "reason": "ai_tagging_enabled=false"}

    general_threshold = await get_float_setting("setting:tag_general_threshold", settings.tag_general_threshold)
    character_threshold = await get_float_setting("setting:tag_character_threshold", settings.tag_character_threshold)

    logger.info("[tag] gallery_id=%d", gallery_id)

    from sqlalchemy.orm import selectinload

    async with httpx.AsyncClient() as client:
        if not await _tagger_available(client):
            # Raise so SAQ retries on transient outage
            raise RuntimeError(f"tagger unavailable for gallery_id={gallery_id}")

        tagged = 0
        async with AsyncSessionLocal() as session:
            images = (
                (
                    await session.execute(
                        select(Image).where(Image.gallery_id == gallery_id).options(selectinload(Image.blob))
                    )
                )
                .scalars()
                .all()
            )

            # Retire stale AI tags first so threshold/model changes shrink the
            # tag set instead of only ever growing it (AIT-006)
            await clear_ai_tags(session, gallery_id)

            for img in images:
                blob = img.blob
                if not blob:
                    continue
                src = resolve_blob_path(blob)
                if not src.exists() or src.suffix.lower() not in _IMAGE_EXTS:
                    continue

                try:
                    results = await _predict_remote(
                        client,
                        str(src),
                        general_threshold,
                        character_threshold,
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

                    existing_keys = {(r.namespace, r.name) for r in tag_rows}
                    missing = [(ns, name) for ns, name, _ in results if (ns, name) not in existing_keys]

                    tag_id_map: dict[tuple[str, str], int] = {(r.namespace, r.name): r.id for r in tag_rows}

                    if missing:
                        for ns, name in missing:
                            row = (
                                await session.execute(select(Tag.id).where(Tag.namespace == ns, Tag.name == name))
                            ).scalar_one_or_none()
                            if row:
                                tag_id_map[(ns, name)] = row

                    # Build confidence map
                    conf_map = {(ns, name): conf for ns, name, conf in results}

                    # Upsert image_tags
                    it_values = []
                    for (ns, name), tid in tag_id_map.items():
                        it_values.append(
                            {
                                "image_id": img.id,
                                "tag_id": tid,
                                "confidence": conf_map.get((ns, name)),
                            }
                        )

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

            # Aggregate AI tags to gallery level
            count = await _aggregate_to_gallery(session, gallery_id, general_threshold)
            await rebuild_gallery_tags_array(session, gallery_id)
            logger.info("[tag] gallery_id=%d: %d tags aggregated to gallery", gallery_id, count)

            await session.commit()

    logger.info("[tag] gallery_id=%d: %d images tagged", gallery_id, tagged)

    from core.events import EventType, emit_safe

    await emit_safe(EventType.GALLERY_TAGGED, resource_type="gallery", resource_id=gallery_id, tags_count=count)

    return {"status": "done", "tagged": tagged}
