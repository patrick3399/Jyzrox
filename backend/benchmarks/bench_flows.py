"""Benchmark flows (queries under test)."""

import sys
import time
from pathlib import Path

from sqlalchemy import Text, cast, desc, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# sys.path — ensure backend/ is importable
# ---------------------------------------------------------------------------

_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ---------------------------------------------------------------------------
from benchmarks.bench_common import (  # noqa: E402
    _BENCH_ITERATIONS,
    BenchResult,
    _run_bench,
    explain_query,
)
from db.models import (  # noqa: E402
    Blob,
    Gallery,
    Image,
    Tag,
    UserFavorite,
    UserRating,
)


async def bench_gallery_list_page1(session: AsyncSession) -> BenchResult:
    """Gallery listing — first page, keyset pagination anchor query."""
    stmt = (
        select(Gallery)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )
    return await _run_bench("gallery_list_page1", "Library Browsing", session, stmt)


async def bench_gallery_list_with_user_state(session: AsyncSession) -> BenchResult:
    """Gallery listing + _get_favorite_set + _get_rating_map (the N+1 pattern)."""
    r = BenchResult(name="gallery_list_with_user_state", flow="Library Browsing")
    user_id = 1

    base_stmt = (
        select(Gallery)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )

    r.explain_plan = await explain_query(session, base_stmt)

    for _ in range(_BENCH_ITERATIONS):
        t0 = time.perf_counter()

        galleries = (await session.execute(base_stmt)).scalars().all()
        gallery_ids = [g.id for g in galleries]

        # _get_favorite_set equivalent
        if gallery_ids:
            fav_stmt = select(UserFavorite.gallery_id).where(
                UserFavorite.user_id == user_id,
                UserFavorite.gallery_id.in_(gallery_ids),
            )
            fav_result = await session.execute(fav_stmt)
            _fav_set = {row[0] for row in fav_result}

        # _get_rating_map equivalent
        if gallery_ids:
            rating_stmt = select(UserRating.gallery_id, UserRating.rating).where(
                UserRating.user_id == user_id,
                UserRating.gallery_id.in_(gallery_ids),
            )
            rating_result = await session.execute(rating_stmt)
            _rating_map = {row[0]: row[1] for row in rating_result}

        r.times_ms.append((time.perf_counter() - t0) * 1000)

    return r


async def bench_gallery_list_cursor_p50(session: AsyncSession) -> BenchResult:
    """Gallery listing via keyset cursor to approximately page 50."""
    r = BenchResult(name="gallery_list_cursor_p50", flow="Library Browsing")

    # Walk 50 pages of 20 to find a real cursor anchor point, then benchmark that step.
    page_stmt = (
        select(Gallery)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )
    rows = (await session.execute(page_stmt)).scalars().all()
    for _page in range(49):
        if not rows:
            break
        last = rows[-1]
        page_stmt = (
            select(Gallery)
            .where(
                Gallery.deleted_at.is_(None),
                Gallery.visibility == "public",
                (Gallery.added_at < last.added_at) | ((Gallery.added_at == last.added_at) & (Gallery.id < last.id)),
            )
            .order_by(desc(Gallery.added_at), desc(Gallery.id))
            .limit(20)
        )
        rows = (await session.execute(page_stmt)).scalars().all()

    # The final page_stmt is the one at ~page 50 — benchmark it.
    r.explain_plan = await explain_query(session, page_stmt)

    for _ in range(_BENCH_ITERATIONS):
        t0 = time.perf_counter()
        result = await session.execute(page_stmt)
        _rows = result.scalars().all()
        r.times_ms.append((time.perf_counter() - t0) * 1000)

    return r


async def bench_gallery_list_deep_offset(session: AsyncSession) -> BenchResult:
    """Gallery listing with OFFSET 4000 (page 200 at limit=20) — shows offset regression."""
    stmt = (
        select(Gallery)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .offset(4000)
        .limit(20)
    )
    return await _run_bench("gallery_list_deep_offset", "Library Browsing", session, stmt)


async def bench_cover_map_batch(session: AsyncSession) -> BenchResult:
    """Batch cover lookup for 20 gallery IDs (page_num == 1)."""
    # Fetch 20 gallery IDs to use as a stable input
    id_rows = (
        await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).order_by(Gallery.id).limit(20))
    ).all()
    gallery_ids = [row[0] for row in id_rows]

    stmt = (
        select(Image.gallery_id, Blob.sha256)
        .join(Blob, Image.blob_sha256 == Blob.sha256)
        .where(Image.gallery_id.in_(gallery_ids), Image.page_num == 1)
    )
    return await _run_bench("cover_map_batch", "Library Browsing", session, stmt)


# ---------------------------------------------------------------------------
# Flow 2: Tag Search
# ---------------------------------------------------------------------------


async def bench_tag_autocomplete(session: AsyncSession) -> BenchResult:
    """Tag autocomplete — ILIKE prefix search on namespace and name."""
    stmt = (
        select(Tag)
        .where((Tag.namespace + ":" + Tag.name).ilike("general:general_00%"))
        .order_by(desc(Tag.count))
        .limit(20)
    )
    return await _run_bench("tag_autocomplete", "Tag Search", session, stmt)


async def bench_search_single_tag(session: AsyncSession) -> BenchResult:
    """GIN array containment — galleries tagged with a single tag."""
    target_tag = "general:general_00001"
    stmt = (
        select(Gallery)
        .where(
            Gallery.deleted_at.is_(None),
            Gallery.tags_array.op("@>")(cast([target_tag], ARRAY(Text))),
        )
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )
    return await _run_bench("search_single_tag", "Tag Search", session, stmt)


async def bench_search_multi_tag(session: AsyncSession) -> BenchResult:
    """GIN array containment — galleries with 3 include tags (AND semantics)."""
    include_tags = ["general:general_00001", "character:character_00002", "artist:artist_00003"]
    stmt = (
        select(Gallery)
        .where(
            Gallery.deleted_at.is_(None),
            Gallery.tags_array.op("@>")(cast(include_tags, ARRAY(Text))),
        )
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )
    return await _run_bench("search_multi_tag", "Tag Search", session, stmt)


async def bench_search_combined(session: AsyncSession) -> BenchResult:
    """Combined filter: tags + source + rating (user_ratings subquery)."""
    user_id = 1
    include_tag = "general:general_00001"
    stmt = (
        select(Gallery)
        .where(
            Gallery.deleted_at.is_(None),
            Gallery.source == "ehentai",
            Gallery.tags_array.op("@>")(cast([include_tag], ARRAY(Text))),
            Gallery.id.in_(
                select(UserRating.gallery_id).where(
                    UserRating.user_id == user_id,
                    UserRating.rating >= 3,
                )
            ),
        )
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(20)
    )
    return await _run_bench("search_combined", "Tag Search", session, stmt)
