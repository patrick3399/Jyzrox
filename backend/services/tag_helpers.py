"""Shared tag helper utilities for routers, services, and worker jobs."""

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import GalleryTag, Image, ImageTag, Tag, TagTranslation


def parse_tag_strings(tags: list[str]) -> list[tuple[str, str]]:
    """Parse 'namespace:name' strings into deduplicated (namespace, name) tuples.

    Bare names without ':' default to namespace='general'.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for tag_str in tags:
        if ":" in tag_str:
            ns, name = tag_str.split(":", 1)
        else:
            ns, name = "general", tag_str
        if (ns, name) not in seen:
            seen.add((ns, name))
            result.append((ns, name))
    return result


async def upsert_metadata_gallery_tags(session, gallery_id: int, tags: list[str]) -> None:
    """Write source-metadata tags as gallery_tags rows for one gallery.

    ``galleries.tags_array`` is a denormalised view of these rows —
    :func:`rebuild_gallery_tags_array` regenerates it from them and will happily
    write an empty array when they are missing. Any writer that sets tags_array
    must therefore write the junction rows in the same transaction, or the next
    rebuild silently discards the metadata (HR-008).

    Does not commit; callers own the transaction.
    """
    if not tags:
        return

    # Deduplicate first so a single statement never carries conflicting rows.
    seen: set[tuple[str, str]] = set()
    tag_values: list[dict] = []
    for tag_str in tags:
        if ":" in tag_str:
            ns, name = tag_str.split(":", 1)
        else:
            ns, name = "general", tag_str
        key = (ns, name)
        if key not in seen:
            seen.add(key)
            tag_values.append({"namespace": ns, "name": name, "count": 1})

    tag_stmt = (
        pg_insert(Tag)
        .values(tag_values)
        .on_conflict_do_update(
            index_elements=["namespace", "name"],
            set_={"count": Tag.count + 1},
        )
        .returning(Tag.id)
    )
    tag_ids = (await session.execute(tag_stmt)).scalars().all()

    gt_values = [{"gallery_id": gallery_id, "tag_id": tid, "confidence": 1.0, "source": "metadata"} for tid in tag_ids]
    if gt_values:
        gt_stmt = pg_insert(GalleryTag).values(gt_values).on_conflict_do_nothing()
        await session.execute(gt_stmt)


async def rebuild_gallery_tags_array(session, gallery_id: int) -> list[str]:
    """
    Rebuild galleries.tags_array from gallery_tags join tags (single source of truth).

    Returns the sorted list that was written to the DB.
    """
    rows = (
        await session.execute(
            text(
                "SELECT t.namespace, t.name"
                " FROM gallery_tags gt"
                " JOIN tags t ON gt.tag_id = t.id"
                " WHERE gt.gallery_id = :gid"
            ),
            {"gid": gallery_id},
        )
    ).all()

    tags_array = sorted(f"{r.namespace}:{r.name}" for r in rows)

    await session.execute(
        text("UPDATE galleries SET tags_array = :arr WHERE id = :gid"),
        {"arr": tags_array, "gid": gallery_id},
    )

    return tags_array


async def clear_ai_tags(session, gallery_id: int) -> int:
    """Remove all AI-derived tags for a gallery (AIT-006).

    Deletes image_tags rows (written exclusively by the AI tag job), strips
    their tag strings from each image's tags_array, and deletes gallery_tags
    rows with source='ai'. 'manual' and 'metadata' gallery tags and non-AI
    tags_array entries are preserved.

    Does not commit and does not rebuild galleries.tags_array — callers do
    both (tag_job re-aggregates first; the clear-ai endpoint rebuilds directly).

    Returns the number of gallery-level AI tag rows removed.
    """
    image_subq = select(Image.id).where(Image.gallery_id == gallery_id)

    stale_rows = (
        await session.execute(
            select(ImageTag.image_id, Tag.namespace, Tag.name)
            .join(Tag, Tag.id == ImageTag.tag_id)
            .where(ImageTag.image_id.in_(image_subq))
        )
    ).all()
    stale_by_image: dict[int, set[str]] = {}
    for row in stale_rows:
        stale_by_image.setdefault(row.image_id, set()).add(f"{row.namespace}:{row.name}")

    if stale_by_image:
        images = (await session.execute(select(Image).where(Image.id.in_(stale_by_image.keys())))).scalars().all()
        for img in images:
            stale = stale_by_image[img.id]
            img.tags_array = [t for t in (img.tags_array or []) if t not in stale]

    await session.execute(delete(ImageTag).where(ImageTag.image_id.in_(image_subq)))

    result = await session.execute(
        delete(GalleryTag).where(GalleryTag.gallery_id == gallery_id, GalleryTag.source == "ai")
    )
    return result.rowcount


async def upsert_tag_translations(session, translations: list[dict]) -> None:
    """
    Batch upsert tag translations with on_conflict_do_nothing to preserve
    any user-curated translations that already exist.

    Each dict must contain: namespace, name, language, translation.
    """
    if not translations:
        return

    stmt = (
        pg_insert(TagTranslation)
        .values(translations)
        .on_conflict_do_nothing(index_elements=["namespace", "name", "language"])
    )
    await session.execute(stmt)


async def rebuild_tag_counts(session) -> int:
    """Recalculate all tags.count from gallery_tags GROUP BY.

    Returns the number of tags updated.
    """
    # Subquery: actual count per tag_id from gallery_tags
    subq = (
        select(
            GalleryTag.tag_id,
            func.count().label("actual_count"),
        )
        .group_by(GalleryTag.tag_id)
        .subquery()
    )

    # Update tags where count differs
    stmt = Tag.__table__.update().where(Tag.id == subq.c.tag_id).values(count=subq.c.actual_count)
    result = await session.execute(stmt)

    # Zero out tags with no gallery_tags entries
    orphan_stmt = (
        Tag.__table__.update()
        .where(~Tag.id.in_(select(GalleryTag.tag_id).distinct()))
        .where(Tag.count > 0)
        .values(count=0)
    )
    await session.execute(orphan_stmt)

    return result.rowcount
