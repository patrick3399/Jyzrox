"""Source-owned tag replacement for the Library Workbench."""

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Gallery, GalleryTag, Tag


async def apply_source_tags(db: AsyncSession, gallery: Gallery, tag_strings: Sequence[str]) -> bool:
    """Replace source-owned tags while preserving manual and AI relationships."""
    from services.tag_helpers import parse_tag_strings

    parsed = parse_tag_strings(list(tag_strings))
    tags: list[Tag] = []
    if parsed:
        tags = (
            (
                await db.execute(
                    select(Tag).where(
                        or_(*[(Tag.namespace == namespace) & (Tag.name == name) for namespace, name in parsed])
                    )
                )
            )
            .scalars()
            .all()
        )
    by_value = {(tag.namespace, tag.name): tag for tag in tags}
    for namespace, name in parsed:
        if (namespace, name) not in by_value:
            tag = Tag(namespace=namespace, name=name, count=0)
            db.add(tag)
            await db.flush()
            by_value[(namespace, name)] = tag

    desired_ids = {tag.id for tag in by_value.values()}
    existing = (await db.execute(select(GalleryTag).where(GalleryTag.gallery_id == gallery.id))).scalars().all()
    source_rows = {row.tag_id: row for row in existing if row.source == "metadata"}
    affected_ids = set(source_rows) | desired_ids
    for tag_id, row in source_rows.items():
        if tag_id not in desired_ids:
            await db.delete(row)
    existing_ids = {row.tag_id for row in existing}
    for tag_id in desired_ids:
        if tag_id not in existing_ids:
            db.add(GalleryTag(gallery_id=gallery.id, tag_id=tag_id, confidence=1.0, source="metadata"))
        elif tag_id in source_rows:
            source_rows[tag_id].confidence = 1.0
    await db.flush()

    rows = (
        await db.execute(
            select(Tag.namespace, Tag.name)
            .join(GalleryTag, GalleryTag.tag_id == Tag.id)
            .where(GalleryTag.gallery_id == gallery.id)
            .order_by(Tag.namespace, Tag.name)
        )
    ).all()
    rebuilt = [f"{row.namespace}:{row.name}" for row in rows]
    changed = rebuilt != list(gallery.tags_array or [])
    gallery.tags_array = rebuilt
    for tag_id in affected_ids:
        count = (
            await db.execute(select(func.count()).select_from(GalleryTag).where(GalleryTag.tag_id == tag_id))
        ).scalar_one()
        tag = next((value for value in by_value.values() if value.id == tag_id), None)
        if tag is None:
            tag = await db.get(Tag, tag_id)
        if tag is not None:
            tag.count = count
    return changed
