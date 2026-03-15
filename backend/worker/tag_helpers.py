"""Shared tag helper utilities for worker jobs."""

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import TagTranslation


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
