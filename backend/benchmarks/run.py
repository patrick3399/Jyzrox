"""
Jyzrox Backend Benchmark

Usage (inside api container):
  docker compose exec api python -m benchmarks.run

Or directly:
  DATABASE_URL=postgresql+asyncpg://vault:pass@postgres:5432/vault python -m benchmarks.run
"""

import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
from sqlalchemy import Text, cast, desc, select, text
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# sys.path — ensure backend/ is importable
# ---------------------------------------------------------------------------

_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from db.models import (  # noqa: E402
    Blob,
    Gallery,
    GalleryTag,
    Image,
    ImageTag,
    Tag,
    UserFavorite,
    UserRating,
)
from benchmarks import seed  # noqa: E402

# ---------------------------------------------------------------------------
# DATABASE_URL parsing
# ---------------------------------------------------------------------------

_raw_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://vault:vault@localhost:5432/vault")
_m = re.match(r"postgresql(?:\+asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", _raw_url)
if _m is None:
    raise RuntimeError(f"Cannot parse DATABASE_URL for benchmarks: {_raw_url!r}")
_DB_USER, _DB_PASS, _DB_HOST, _DB_PORT, _DB_NAME = _m.groups()

_BENCH_DB = "jyzrox_bench"
_BENCH_SA_URL = f"postgresql+asyncpg://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_BENCH_DB}"
_BENCH_PG_DSN = f"postgresql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/{_BENCH_DB}"


_BENCH_ITERATIONS = 20

# ---------------------------------------------------------------------------
# BenchResult dataclass
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    name: str
    flow: str
    times_ms: list[float] = field(default_factory=list)
    explain_plan: dict | None = None

    @property
    def p50(self) -> float:
        s = sorted(self.times_ms)
        return s[len(s) // 2] if s else 0.0

    @property
    def p95(self) -> float:
        s = sorted(self.times_ms)
        return s[int(len(s) * 0.95)] if s else 0.0

    @property
    def p99(self) -> float:
        s = sorted(self.times_ms)
        return s[int(len(s) * 0.99)] if s else 0.0


# ---------------------------------------------------------------------------
# DB lifecycle
# ---------------------------------------------------------------------------


async def setup_bench_db() -> str:
    """Create jyzrox_bench, apply init.sql schema. Returns the asyncpg DSN."""
    admin_dsn = f"postgresql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/postgres"
    admin_conn = await asyncpg.connect(admin_dsn)
    try:
        await admin_conn.execute(f"DROP DATABASE IF EXISTS {_BENCH_DB}")
        await admin_conn.execute(f"CREATE DATABASE {_BENCH_DB}")
    finally:
        await admin_conn.close()

    # Create all tables from SQLAlchemy model metadata
    from core.database import Base  # noqa: PLC0415

    engine = create_async_engine(_BENCH_SA_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    # Apply custom indexes from init.sql that aren't in SQLAlchemy metadata
    bench_conn = await asyncpg.connect(_BENCH_PG_DSN)
    try:
        await bench_conn.execute("""
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE INDEX IF NOT EXISTS idx_galleries_tags_gin ON galleries USING GIN (tags_array);
            CREATE INDEX IF NOT EXISTS idx_images_tags_gin ON images USING GIN (tags_array);
            CREATE INDEX IF NOT EXISTS idx_galleries_title_trgm ON galleries USING GIN (title gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_galleries_added_at_id ON galleries (added_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_galleries_rating_id ON galleries (rating DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_images_added_at_id ON images (added_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_images_gallery_added_at_id ON images (gallery_id, added_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_galleries_live_added_at_id ON galleries (added_at DESC, id DESC) WHERE deleted_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_galleries_public_added_at_id ON galleries (added_at DESC, id DESC) WHERE deleted_at IS NULL AND visibility = 'public';
            CREATE INDEX IF NOT EXISTS idx_galleries_owner_added_at_id ON galleries (created_by_user_id, added_at DESC, id DESC) WHERE deleted_at IS NULL AND created_by_user_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_tags_count ON tags (count DESC);
            CREATE INDEX IF NOT EXISTS idx_gallery_tags_tag ON gallery_tags (tag_id);
            CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags (tag_id);
            CREATE INDEX IF NOT EXISTS idx_galleries_source ON galleries (source, source_id);
            CREATE INDEX IF NOT EXISTS idx_galleries_visibility ON galleries (visibility);
            CREATE INDEX IF NOT EXISTS idx_galleries_created_by ON galleries (created_by_user_id) WHERE created_by_user_id IS NOT NULL;
        """)
    finally:
        await bench_conn.close()

    return _BENCH_PG_DSN


async def teardown_bench_db() -> None:
    """Drop jyzrox_bench."""
    admin_dsn = f"postgresql://{_DB_USER}:{_DB_PASS}@{_DB_HOST}:{_DB_PORT}/postgres"
    admin_conn = await asyncpg.connect(admin_dsn)
    try:
        await admin_conn.execute(f"DROP DATABASE IF EXISTS {_BENCH_DB}")
    finally:
        await admin_conn.close()


# ---------------------------------------------------------------------------
# EXPLAIN helper
# ---------------------------------------------------------------------------


async def explain_query(session: AsyncSession, stmt) -> dict | None:
    """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and return the parsed plan."""
    from sqlalchemy.dialects import postgresql

    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    raw = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled.string}"
    result = await session.execute(text(raw))
    return result.scalar()


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------


async def _run_bench(
    name: str,
    flow: str,
    session: AsyncSession,
    stmt,
) -> BenchResult:
    """Run EXPLAIN + timing loop for a single pre-built statement."""
    r = BenchResult(name=name, flow=flow)
    r.explain_plan = await explain_query(session, stmt)
    for _ in range(_BENCH_ITERATIONS):
        t0 = time.perf_counter()
        await session.execute(stmt)
        r.times_ms.append((time.perf_counter() - t0) * 1000)
    return r


# ---------------------------------------------------------------------------
# Flow 1: Library Browsing
# ---------------------------------------------------------------------------


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
                (Gallery.added_at < last.added_at)
                | ((Gallery.added_at == last.added_at) & (Gallery.id < last.id)),
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
        await session.execute(
            select(Gallery.id)
            .where(Gallery.deleted_at.is_(None))
            .order_by(Gallery.id)
            .limit(20)
        )
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
        .where(
            (Tag.namespace + ":" + Tag.name).ilike("general:general_00%")
        )
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


# ---------------------------------------------------------------------------
# Flow 3: Gallery Images
# ---------------------------------------------------------------------------


async def bench_gallery_detail(session: AsyncSession) -> BenchResult:
    """Single gallery lookup by primary key."""
    gid_row = (
        await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))
    ).first()
    gid = gid_row[0] if gid_row else 1
    stmt = select(Gallery).where(Gallery.id == gid)
    return await _run_bench("gallery_detail", "Gallery Images", session, stmt)


async def bench_gallery_images_page1(session: AsyncSession) -> BenchResult:
    """Images for a single gallery — first page of 40."""
    gid_row = (
        await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))
    ).first()
    gid = gid_row[0] if gid_row else 1
    stmt = (
        select(Image)
        .where(Image.gallery_id == gid)
        .order_by(Image.page_num)
        .limit(40)
    )
    return await _run_bench("gallery_images_page1", "Gallery Images", session, stmt)


async def bench_gallery_tags(session: AsyncSession) -> BenchResult:
    """Gallery tags for a single gallery (gallery_tags JOIN tags)."""
    gid_row = (
        await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))
    ).first()
    gid = gid_row[0] if gid_row else 1
    stmt = (
        select(GalleryTag, Tag)
        .join(Tag, GalleryTag.tag_id == Tag.id)
        .where(GalleryTag.gallery_id == gid)
        .order_by(desc(GalleryTag.confidence))
    )
    return await _run_bench("gallery_tags", "Gallery Images", session, stmt)


async def bench_image_browser_cross(session: AsyncSession) -> BenchResult:
    """Cross-gallery image browser — newest images across all galleries, limit 40."""
    stmt = (
        select(Image)
        .join(Gallery, Image.gallery_id == Gallery.id)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Image.added_at), desc(Image.id))
        .limit(40)
    )
    return await _run_bench("image_browser_cross", "Gallery Images", session, stmt)


# ---------------------------------------------------------------------------
# Flow 4: Explorer
# ---------------------------------------------------------------------------


async def bench_explorer_galleries_by_source(session: AsyncSession) -> BenchResult:
    """Explorer: galleries filtered by source='ehentai'."""
    stmt = (
        select(Gallery)
        .where(Gallery.source == "ehentai", Gallery.deleted_at.is_(None))
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(40)
    )
    return await _run_bench("explorer_galleries_by_source", "Explorer", session, stmt)


async def bench_explorer_gallery_images(session: AsyncSession) -> BenchResult:
    """Explorer: all images for a specific gallery (no page limit)."""
    gid_row = (
        await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))
    ).first()
    gid = gid_row[0] if gid_row else 1
    stmt = (
        select(Image.id, Image.page_num, Image.filename, Image.blob_sha256)
        .where(Image.gallery_id == gid)
        .order_by(Image.page_num)
    )
    return await _run_bench("explorer_gallery_images", "Explorer", session, stmt)


# ---------------------------------------------------------------------------
# Flow 5: Worker Pressure
# ---------------------------------------------------------------------------


async def bench_dedup_load_blobs(session: AsyncSession) -> BenchResult:
    """Dedup worker: load sha256 + phash_int for all blobs with a known pHash."""
    stmt = (
        select(Blob.sha256, Blob.phash_int)
        .where(Blob.phash_int.is_not(None))
        .order_by(Blob.sha256)
        .limit(10_000)
    )
    return await _run_bench("dedup_load_blobs", "Worker Pressure", session, stmt)


async def bench_tag_upsert_batch(session: AsyncSession) -> BenchResult:
    """
    Worker pressure: INSERT image_tags for 100 images x 3 tags each.
    Uses INSERT ... ON CONFLICT DO NOTHING to simulate tagger output.
    """
    r = BenchResult(name="tag_upsert_batch", flow="Worker Pressure")

    # Fetch stable image and tag IDs for the upsert input.
    image_id_rows = (
        await session.execute(select(Image.id).order_by(Image.id).limit(100))
    ).all()
    tag_id_rows = (
        await session.execute(select(Tag.id).order_by(Tag.id).limit(3))
    ).all()

    image_ids = [row[0] for row in image_id_rows]
    tag_ids = [row[0] for row in tag_id_rows]

    upsert_stmt = (
        pg_insert(ImageTag)
        .values([
            {"image_id": img_id, "tag_id": tag_id, "confidence": 0.9}
            for img_id in image_ids
            for tag_id in tag_ids
        ])
        .on_conflict_do_nothing()
    )

    r.explain_plan = None  # INSERT EXPLAIN plans are not meaningful here

    for _ in range(_BENCH_ITERATIONS):
        t0 = time.perf_counter()
        await session.execute(upsert_stmt)
        await session.rollback()  # Roll back so data stays stable across iterations
        r.times_ms.append((time.perf_counter() - t0) * 1000)

    return r


# ---------------------------------------------------------------------------
# Summary table printer
# ---------------------------------------------------------------------------

_ALL_BENCHMARKS = [
    bench_gallery_list_page1,
    bench_gallery_list_with_user_state,
    bench_gallery_list_cursor_p50,
    bench_gallery_list_deep_offset,
    bench_cover_map_batch,
    bench_tag_autocomplete,
    bench_search_single_tag,
    bench_search_multi_tag,
    bench_search_combined,
    bench_gallery_detail,
    bench_gallery_images_page1,
    bench_gallery_tags,
    bench_image_browser_cross,
    bench_explorer_galleries_by_source,
    bench_explorer_gallery_images,
    bench_dedup_load_blobs,
    bench_tag_upsert_batch,
]


def print_summary(results: list[BenchResult]) -> None:
    print("\n")
    print("=" * 80)
    print("Jyzrox Benchmark Results")
    print("=" * 80)
    current_flow = ""
    print(f"{'Benchmark':<35} {'p50':>8} {'p95':>8} {'p99':>8}")
    print("-" * 65)
    for r in results:
        if r.flow != current_flow:
            current_flow = r.flow
            print(f"\n  {current_flow}")
        plan_hint = ""
        if r.explain_plan:
            plan_str = str(r.explain_plan)
            if "Seq Scan" in plan_str:
                plan_hint = "  [WARN: seq scan]"
            elif "Index" in plan_str:
                plan_hint = "  [idx]"
        print(f"  {r.name:<33} {r.p50:>7.1f}ms {r.p95:>7.1f}ms {r.p99:>7.1f}ms{plan_hint}")
    print("=" * 80)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def main() -> None:
    print("Setting up benchmark database...")
    await setup_bench_db()

    engine = create_async_engine(
        _BENCH_SA_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        print("Seeding benchmark data...")
        counts = await seed.seed_all(_BENCH_PG_DSN)
        print(f"Seed complete: {sum(counts.values()):,} total rows\n")

        results: list[BenchResult] = []
        async with factory() as session:
            for bench_fn in _ALL_BENCHMARKS:
                r = await bench_fn(session)
                results.append(r)
                print(
                    f"  {r.name:<35} "
                    f"p50={r.p50:>7.1f}ms  "
                    f"p95={r.p95:>7.1f}ms  "
                    f"p99={r.p99:>7.1f}ms"
                )

        print_summary(results)

    finally:
        await engine.dispose()
        print("\nDropping benchmark database...")
        await teardown_bench_db()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
