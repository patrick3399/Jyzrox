"""Shared gallery enrichment helpers used by library and search routers."""

from sqlalchemy import asc, desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.source_display import get_display_config
from db.models import ExcludedBlob, Image, UserFavorite, UserRating, UserReadingList
from services.cas import thumb_dir
from services.cas import thumb_url as cas_thumb_url


def _existing_thumb_url(sha256: str) -> str | None:
    if (thumb_dir(sha256) / "thumb_160.webp").exists():
        return cas_thumb_url(sha256)
    return None


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

    rows = (await db.execute(select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id))).all()
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
    cover_sha_map = await build_cover_sha_map(db, gallery_ids, source_map)
    cover_map: dict[int, str] = {}
    for gallery_id, sha256 in cover_sha_map.items():
        thumb_url = _existing_thumb_url(sha256)
        if thumb_url:
            cover_map[gallery_id] = thumb_url
    return cover_map


def image_not_excluded_clause():
    """SQL clause selecting images whose blob is not excluded for its gallery."""
    excluded_sq = (
        select(ExcludedBlob.blob_sha256)
        .where(ExcludedBlob.gallery_id == Image.gallery_id)
        .where(ExcludedBlob.blob_sha256 == Image.blob_sha256)
        .correlate(Image)
    )
    return ~exists(excluded_sq)


async def select_cover_images(
    db: AsyncSession,
    gallery_ids: list[int],
    source_map: dict[int, str] | None = None,
) -> dict[int, Image]:
    """Return gallery_id -> configured active cover image, excluding blocked blobs."""
    if not gallery_ids:
        return {}

    first_ids: list[int] = []
    last_ids: list[int] = []
    for gid in gallery_ids:
        cfg = get_display_config((source_map or {}).get(gid, ""))
        if cfg.cover_page == "last":
            last_ids.append(gid)
        else:
            first_ids.append(gid)

    cover_images: dict[int, Image] = {}

    async def _load(ids: list[int], newest: bool) -> None:
        if not ids:
            return
        order = (desc(Image.page_num), desc(Image.id)) if newest else (asc(Image.page_num), asc(Image.id))
        rank_sub = (
            select(
                Image.id.label("image_id"),
                Image.gallery_id.label("gallery_id"),
                func.row_number().over(partition_by=Image.gallery_id, order_by=order).label("rn"),
            )
            .where(
                Image.gallery_id.in_(ids),
                Image.visibility == "active",
                image_not_excluded_clause(),
            )
            .subquery()
        )
        rows = (
            (
                await db.execute(
                    select(Image)
                    .join(rank_sub, Image.id == rank_sub.c.image_id)
                    .where(rank_sub.c.rn == 1)
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )
        for img in rows:
            cover_images[img.gallery_id] = img

    await _load(first_ids, newest=False)
    await _load(last_ids, newest=True)
    return cover_images


async def select_cover_image(
    db: AsyncSession,
    gallery_id: int,
    source: str,
) -> Image | None:
    """Return the configured active cover image for one gallery."""
    return (await select_cover_images(db, [gallery_id], {gallery_id: source})).get(gallery_id)


async def build_cover_sha_map(
    db: AsyncSession,
    gallery_ids: list[int],
    source_map: dict[int, str] | None = None,
) -> dict[int, str]:
    """Build gallery_id -> cover blob sha256 map using shared cover rules."""
    images = await select_cover_images(db, gallery_ids, source_map)
    return {gallery_id: img.blob_sha256 for gallery_id, img in images.items() if img.blob_sha256}
