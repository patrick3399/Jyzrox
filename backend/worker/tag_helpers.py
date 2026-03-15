"""Shared tag helper utilities for worker jobs."""

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import GalleryTag, Tag, TagTranslation


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
    stmt = (
        Tag.__table__.update()
        .where(Tag.id == subq.c.tag_id)
        .values(count=subq.c.actual_count)
    )
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
