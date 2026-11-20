"""
Benchmark data seeder for Jyzrox.

Generates synthetic data at scale using asyncpg COPY for maximum throughput.
All random operations use a fixed seed (42) for reproducibility.

Scale targets:
  users:        3
  tags:         10,000
  blobs:        200,000
  galleries:    10,000
  images:       ~1,000,000 (50-200 per gallery)
  gallery_tags: ~100,000 (5-15 per gallery, deduplicated)
  favorites:    ~1,000
  ratings:      ~2,000
"""

import random
import time

import asyncpg

from benchmarks.seed_phases import (
    _phase_blobs,
    _phase_galleries,
    _phase_gallery_tags,
    _phase_images,
    _phase_tags,
    _phase_user_data,
    _phase_users,
)

random.seed(42)

# Public entry point
# ---------------------------------------------------------------------------


async def seed_all(dsn: str) -> dict[str, int]:
    """
    Seed the benchmark database at dsn with synthetic data.
    Returns a dict of {phase_name: row_count}.

    Uses a raw asyncpg connection directly (not SQLAlchemy) for maximum
    COPY throughput.
    """
    conn = await asyncpg.connect(dsn)
    counts: dict[str, int] = {}

    try:

        async def _timed(name: str, coro):
            t0 = time.perf_counter()
            result = await coro
            elapsed = time.perf_counter() - t0
            n = result[0] if isinstance(result, tuple) else result
            counts[name] = n
            print(f"  [seed] {name}: {n:,} rows in {elapsed:.1f}s")
            return result

        await _timed("users", _phase_users(conn))
        await _timed("tags", _phase_tags(conn))
        _, blob_shas = await _timed("blobs", _phase_blobs(conn))
        _, gallery_rows = await _timed("galleries", _phase_galleries(conn))

        await _timed("images", _phase_images(conn, gallery_rows, blob_shas))
        await _timed("gallery_tags", _phase_gallery_tags(conn, gallery_rows))
        await _timed("user_data", _phase_user_data(conn, gallery_rows))

    finally:
        await conn.close()

    return counts
