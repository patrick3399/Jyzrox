"""
Jyzrox Backend Benchmark

Usage (inside api container):
  docker compose exec api python -m benchmarks.run

Or directly:
  DATABASE_URL=postgresql+asyncpg://vault:pass@postgres:5432/vault python -m benchmarks.run
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# sys.path — ensure backend/ is importable
# ---------------------------------------------------------------------------

_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from benchmarks import seed  # noqa: E402

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
from benchmarks.bench_common import (  # noqa: E402
    _BENCH_PG_DSN,
    _BENCH_SA_URL,
    BenchResult,
    setup_bench_db,
    teardown_bench_db,
)
from benchmarks.bench_flows import (  # noqa: E402
    bench_cover_map_batch,
    bench_gallery_list_cursor_p50,
    bench_gallery_list_deep_offset,
    bench_gallery_list_page1,
    bench_gallery_list_with_user_state,
    bench_search_combined,
    bench_search_multi_tag,
    bench_search_single_tag,
    bench_tag_autocomplete,
)
from benchmarks.bench_flows_detail import (  # noqa: E402
    bench_dedup_load_blobs,
    bench_explorer_galleries_by_source,
    bench_explorer_gallery_images,
    bench_gallery_detail,
    bench_gallery_images_page1,
    bench_gallery_tags,
    bench_image_browser_cross,
)

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
                print(f"  {r.name:<35} p50={r.p50:>7.1f}ms  p95={r.p95:>7.1f}ms  p99={r.p99:>7.1f}ms")

        print_summary(results)

    finally:
        await engine.dispose()
        print("\nDropping benchmark database...")
        await teardown_bench_db()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
