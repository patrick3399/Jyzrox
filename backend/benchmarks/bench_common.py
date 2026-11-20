"""Shared benchmark configuration, result type, DB setup and timing helpers."""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------------------------------------------------------------------------
# sys.path — ensure backend/ is importable
# ---------------------------------------------------------------------------

_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


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
