"""Shared gallery enrichment helpers used by library and search routers."""

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.source_display import get_display_config
from db.models import Blob, Image, UserFavorite, UserRating, UserReadingList
from services.cas import thumb_url as cas_thumb_url


async def get_favorite_set(db: AsyncSession, user_id: int, gallery_ids: list[int]) -> set[int]:
    """Return set of gallery_ids that are favorited by this user."""
    if not gallery_ids:
        return set()
    result = await db.execute(
        select(UserFavorite.gallery_id).where(
            UserFavorite.user_id == user_id,
            UserFavorite.gallery_id.in_(gallery_ids),
        )
    )
    return {row[0] for row in result}


async def get_reading_list_set(db: AsyncSession, user_id: int, gallery_ids: list[int]) -> set[int]:
    """Return set of gallery_ids that are in this user's reading list."""
    if not gallery_ids:
        return set()
    result = await db.execute(
        select(UserReadingList.gallery_id).where(
            UserReadingList.user_id == user_id,
            UserReadingList.gallery_id.in_(gallery_ids),
        )
    )
    return {row[0] for row in result}


async def get_rating_map(db: AsyncSession, user_id: int, gallery_ids: list[int]) -> dict[int, int]:
    """Return {gallery_id: rating} for this user."""
    if not gallery_ids:
        return {}
    result = await db.execute(
        select(UserRating.gallery_id, UserRating.rating).where(
            UserRating.user_id == user_id,
            UserRating.gallery_id.in_(gallery_ids),
        )
    )
    return {row[0]: row[1] for row in result}


async def get_blocked_tag_strings(db: AsyncSession, user_id: int) -> list[str]:
    """Return list of 'namespace:name' blocked tag strings for the user."""
    from db.models import BlockedTag

    rows = (
        await db.execute(
            select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id)
        )
    ).all()
    return [f"{r.namespace}:{r.name}" for r in rows]


async def build_cover_map(
    db: AsyncSession,
    gallery_ids: list[int],
    source_map: dict[int, str] | None = None,
) -> dict[int, str]:
    """Build gallery_id -> cover_thumb_url map, respecting per-source cover_page config.

    Args:
        db: Database session.
        gallery_ids: Gallery IDs to fetch covers for.
        source_map: Optional {gallery_id: source} mapping. If None, all use page_num=1.
    """
    if not gallery_ids:
        return {}

    # Split galleries by cover strategy
    first_ids: list[int] = []
    last_ids: list[int] = []
    for gid in gallery_ids:
        source = (source_map or {}).get(gid, "")
        cfg = get_display_config(source)
        if cfg.cover_page == "last":
            last_ids.append(gid)
        else:
            first_ids.append(gid)

    cover_map: dict[int, str] = {}

    # Batch query: first page covers
    if first_ids:
        stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .where(Image.gallery_id.in_(first_ids), Image.page_num == 1)
        )
        for r in (await db.execute(stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)

    # Batch query: last page covers
    if last_ids:
        max_page_sub = (
            select(Image.gallery_id, func.max(Image.page_num).label("max_page"))
            .where(Image.gallery_id.in_(last_ids))
            .group_by(Image.gallery_id)
        ).subquery()
        stmt = (
            select(Image.gallery_id, Blob.sha256)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .join(
                max_page_sub,
                and_(
                    Image.gallery_id == max_page_sub.c.gallery_id,
                    Image.page_num == max_page_sub.c.max_page,
                ),
            )
        )
        for r in (await db.execute(stmt)).all():
            cover_map[r.gallery_id] = cas_thumb_url(r.sha256)

    return cover_map
