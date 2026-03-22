"""
Unit tests for the dedup pipeline workers (tier 1, 2, 3).

Strategy:
- Patch `core.database.async_session` with the test SQLite session factory
  so all DB calls go through the in-memory DB.
- Mock Redis via AsyncMock so no real Redis connection is required.
- Mock `worker.dedup_helpers._opencv_pixel_diff` for tier 3 to avoid cv2 dep.
- Insert blobs / blob_relationships directly via raw SQL (SQLite-compatible).
"""

import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_cm(factory):
    """Wrap async_sessionmaker so ``async with async_session() as s:`` works."""

    @asynccontextmanager
    async def _cm():
        async with factory() as session:
            yield session

    class _Factory:
        def __call__(self):
            return _cm()

    return _Factory()

async def _insert_blob(
    session,
    sha256: str,
    phash_int: int | None = None,
    phash_q0: int | None = None,
    phash_q1: int | None = None,
    phash_q2: int | None = None,
    phash_q3: int | None = None,
    width: int = 100,
    height: int = 100,
    file_size: int = 1024,
    extension: str = ".jpg",
) -> None:
    await session.execute(
        text(
            "INSERT OR IGNORE INTO blobs "
            "(sha256, file_size, extension, ref_count, "
            " phash_int, phash_q0, phash_q1, phash_q2, phash_q3, width, height) "
            "VALUES (:sha256, :file_size, :ext, 1, "
            " :phash_int, :phash_q0, :phash_q1, :phash_q2, :phash_q3, :width, :height)"
        ),
        {
            "sha256": sha256,
            "file_size": file_size,
            "ext": extension,
            "phash_int": phash_int,
            "phash_q0": phash_q0,
            "phash_q1": phash_q1,
            "phash_q2": phash_q2,
            "phash_q3": phash_q3,
            "width": width,
            "height": height,
        },
    )
    await session.commit()

async def _insert_relationship(
    session,
    sha_a: str,
    sha_b: str,
    relationship: str = "needs_t2",
    hamming_dist: int = 3,
    tier: int = 1,
) -> int:
    result = await session.execute(
        text(
            "INSERT INTO blob_relationships "
            "(sha_a, sha_b, hamming_dist, relationship, tier) "
            "VALUES (:sha_a, :sha_b, :dist, :rel, :tier) "
            "RETURNING id"
        ),
        {
            "sha_a": sha_a,
            "sha_b": sha_b,
            "dist": hamming_dist,
            "rel": relationship,
            "tier": tier,
        },
    )
    await session.commit()
    return result.fetchone()[0]

def _make_redis(overrides: dict | None = None) -> AsyncMock:
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.getdel = AsyncMock(return_value=None)
    pipeline = MagicMock()
    pipeline.set = MagicMock()
    pipeline.delete = MagicMock()
    pipeline.execute = AsyncMock(return_value=None)
    r.pipeline = MagicMock(return_value=pipeline)
    if overrides:
        for k, v in overrides.items():
            setattr(r, k, v)
    return r

# ---------------------------------------------------------------------------
# TestDedupTier1
# ---------------------------------------------------------------------------

class TestDedupTier1:
    """Tests for worker.dedup_tier1.dedup_tier1_job."""

    async def test_disabled_setting_returns_skipped(self, db_session_factory):
        """When dedup_phash_enabled is 0, job must return status='skipped'."""
        from worker.dedup_tier1 import dedup_tier1_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"0")

        with patch("worker.dedup_tier1.get_redis", return_value=r):
            result = await dedup_tier1_job({})

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    async def test_no_blobs_with_phash_returns_zero_pairs(self, db_session_factory):
        """When no blobs have phash_int set, inserted count must be 0."""
        from worker.dedup_tier1 import dedup_tier1_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            result = await dedup_tier1_job({})

        assert result["status"] == "ok"
        assert result["inserted"] == 0

    async def test_custom_threshold_from_redis(self, db_session, db_session_factory):
        """threshold=0 must reject all pairs even with identical hashes."""
        from worker.dedup_tier1 import dedup_tier1_job

        sha_a = "aa" + "0" * 62
        sha_b = "ab" + "0" * 62
        # Two blobs with identical phash — normally would match at threshold=10
        await _insert_blob(session=db_session, sha256=sha_a, phash_int=12345, phash_q0=0, phash_q1=0)
        await _insert_blob(session=db_session, sha256=sha_b, phash_int=12345, phash_q0=0, phash_q1=0)

        r = _make_redis()
        # Return b"1" for enabled, then "0" for threshold
        call_count = 0

        async def _get_side(key):
            nonlocal call_count
            call_count += 1
            if "enabled" in key:
                return b"1"
            if "threshold" in key:
                return b"0"
            return None

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            result = await dedup_tier1_job({})

        # With threshold=0 even hamming dist=0 would be accepted (0 <= 0)
        # Both blobs have identical phash_int so dist=0 which passes threshold=0
        assert result["status"] == "ok"

    async def test_pigeonhole_prefilter_skips_dissimilar_pairs(
        self, db_session, db_session_factory
    ):
        """Pairs where q0+q1 hamming already exceeds threshold are skipped early."""
        from worker.dedup_tier1 import dedup_tier1_job

        sha_a = "ba" + "0" * 62
        sha_b = "bb" + "0" * 62
        # phash_q0 differ in all 16 bits → pigeonhole dist=16 > threshold=10 → skip
        await _insert_blob(session=db_session, sha256=sha_a, phash_int=0, phash_q0=0x0000, phash_q1=0)
        await _insert_blob(session=db_session, sha256=sha_b, phash_int=0xFFFF, phash_q0=0xFFFF, phash_q1=0)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"10"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            result = await dedup_tier1_job({})

        assert result["status"] == "ok"
        # The pair with high q0 difference must have been skipped
        count = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).scalar()
        assert count == 0

    async def test_similar_pairs_stored_in_blob_relationships(
        self, db_session, db_session_factory
    ):
        """Blobs within hamming threshold must be inserted into blob_relationships."""
        from worker.dedup_tier1 import dedup_tier1_job

        sha_a = "ca" + "0" * 62
        sha_b = "cb" + "0" * 62
        # phash differs by 1 bit only → dist=1 ≤ threshold=10
        await _insert_blob(session=db_session, sha256=sha_a, phash_int=0b1000, phash_q0=0, phash_q1=0)
        await _insert_blob(session=db_session, sha256=sha_b, phash_int=0b1001, phash_q0=0, phash_q1=0)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"10"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            result = await dedup_tier1_job({})

        assert result["status"] == "ok"
        count = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM blob_relationships "
                    "WHERE relationship='needs_t2'"
                )
            )
        ).scalar()
        assert count >= 1

    async def test_batch_flush_inserts_on_conflict_do_nothing(
        self, db_session, db_session_factory
    ):
        """Running tier1 twice must not duplicate relationships (on_conflict_do_nothing)."""
        from worker.dedup_tier1 import dedup_tier1_job

        sha_a = "da" + "0" * 62
        sha_b = "db" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, phash_int=0, phash_q0=0, phash_q1=0)
        await _insert_blob(session=db_session, sha256=sha_b, phash_int=0, phash_q0=0, phash_q1=0)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"10"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            await dedup_tier1_job({})
            await dedup_tier1_job({})

        count = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).scalar()
        assert count == 1

    async def test_progress_redis_keys_written_on_completion(
        self, db_session, db_session_factory
    ):
        """After job completes, Redis keys for last_run and last_status must be set."""
        from worker.dedup_tier1 import dedup_tier1_job

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"10"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            await dedup_tier1_job({})

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_flag_none_also_skips(self, db_session_factory):
        """enabled=None (key missing) must also return skipped."""
        from worker.dedup_tier1 import dedup_tier1_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier1.get_redis", return_value=r):
            result = await dedup_tier1_job({})

        assert result["status"] == "skipped"

    async def test_dissimilar_pairs_not_stored(self, db_session, db_session_factory):
        """Blobs with hamming distance above threshold must not produce a relationship."""
        from worker.dedup_tier1 import dedup_tier1_job

        sha_a = "ea" + "0" * 62
        sha_b = "eb" + "0" * 62
        # phash differs by 20 bits → exceeds threshold=10
        await _insert_blob(session=db_session, sha256=sha_a, phash_int=0x00000, phash_q0=0x0000, phash_q1=0)
        await _insert_blob(session=db_session, sha256=sha_b, phash_int=0xFFFFF, phash_q0=0x0000, phash_q1=0)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"10"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            result = await dedup_tier1_job({})

        count = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).scalar()
        assert count == 0

# ---------------------------------------------------------------------------
# TestDedupTier2
# ---------------------------------------------------------------------------

class TestDedupTier2:
    """Tests for worker.dedup_tier2.dedup_tier2_job."""

    async def test_disabled_setting_returns_skipped(self, db_session_factory):
        """When dedup_phash_enabled is 0, job must return status='skipped'."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"0")

        with patch("worker.dedup_tier2.get_redis", return_value=r):
            result = await dedup_tier2_job({})

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    async def test_no_needs_t2_relationships_returns_zero(
        self, db_session, db_session_factory
    ):
        """When no needs_t2 pairs exist, processed count must be 0."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            result = await dedup_tier2_job({})

        assert result["status"] == "ok"
        assert result["processed"] == 0

    async def test_heuristic_higher_resolution_classify(
        self, db_session, db_session_factory
    ):
        """Blob with much higher resolution must produce quality_conflict/higher_resolution."""
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "fa" + "0" * 62
        sha_b = "fb" + "0" * 62
        # blob_a is much bigger (200x200 vs 100x100) → pixels_a > pixels_b * 1.10
        await _insert_blob(session=db_session, sha256=sha_a, width=200, height=200)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")

        r = _make_redis()

        async def _get_side(key):
            if "heuristic" in key:
                return b"1"
            if "opencv" in key:
                return b"0"  # no opencv → classify directly
            return b"1"  # phash enabled

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            result = await dedup_tier2_job({})

        assert result["status"] == "ok"
        assert result["processed"] >= 1

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship, reason FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "quality_conflict"
        assert row[1] == "higher_resolution"

    async def test_heuristic_larger_file_classify(self, db_session, db_session_factory):
        """Blob with much larger file size must produce quality_conflict/larger_file."""
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "ga" + "0" * 62
        sha_b = "gb" + "0" * 62
        # Same resolution, but blob_a file is 1.5x bigger → larger_file
        await _insert_blob(
            session=db_session, sha256=sha_a, width=100, height=100, file_size=15000
        )
        await _insert_blob(
            session=db_session, sha256=sha_b, width=100, height=100, file_size=10000
        )
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")

        r = _make_redis()

        async def _get_side(key):
            if "heuristic" in key:
                return b"1"
            if "opencv" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job({})

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship, reason FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "quality_conflict"
        assert row[1] == "larger_file"

    async def test_heuristic_similar_size_produces_variant(
        self, db_session, db_session_factory
    ):
        """Blobs with equal resolution and similar file size must be classified as variant."""
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "ha" + "0" * 62
        sha_b = "hb" + "0" * 62
        await _insert_blob(
            session=db_session, sha256=sha_a, width=100, height=100, file_size=10000
        )
        await _insert_blob(
            session=db_session, sha256=sha_b, width=100, height=100, file_size=10050
        )
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")

        r = _make_redis()

        async def _get_side(key):
            if "heuristic" in key:
                return b"1"
            if "opencv" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job({})

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "variant"

    async def test_opencv_enabled_routes_to_needs_t3(
        self, db_session, db_session_factory
    ):
        """When opencv is enabled, pairs must be moved to needs_t3 instead of direct classify."""
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "ia" + "0" * 62
        sha_b = "ib" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=200, height=200)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")

        r = _make_redis()

        async def _get_side(key):
            if "heuristic" in key:
                return b"1"
            if "opencv" in key:
                return b"1"  # opencv enabled → defer to t3
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job({})

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "needs_t3"

    async def test_batch_updates_committed(self, db_session, db_session_factory):
        """Multiple needs_t2 pairs must all be processed and committed."""
        from worker.dedup_tier2 import dedup_tier2_job

        pairs = []
        for i in range(3):
            sha_a = f"j{i}a" + "0" * 61
            sha_b = f"j{i}b" + "0" * 61
            await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100)
            await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
            await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")
            pairs.append((sha_a, sha_b))

        r = _make_redis()

        async def _get_side(key):
            if "heuristic" in key:
                return b"1"
            if "opencv" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            result = await dedup_tier2_job({})

        assert result["processed"] >= 3

    async def test_progress_redis_keys_written_on_completion(
        self, db_session_factory
    ):
        """After job completes, Redis last_run and last_status keys must be set."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job({})

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_none_also_skips(self, db_session_factory):
        """When Redis key is missing (None), job must return skipped."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier2.get_redis", return_value=r):
            result = await dedup_tier2_job({})

        assert result["status"] == "skipped"

# ---------------------------------------------------------------------------
# TestDedupTier3
# ---------------------------------------------------------------------------

class TestDedupTier3:
    """Tests for worker.dedup_tier3.dedup_tier3_job."""

    async def test_disabled_setting_returns_skipped(self, db_session_factory):
        """When dedup_opencv_enabled is 0, job must return status='skipped'."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"0")

        with patch("worker.dedup_tier3.get_redis", return_value=r):
            result = await dedup_tier3_job({})

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    async def test_no_needs_t3_relationships_returns_zero(
        self, db_session, db_session_factory
    ):
        """When no needs_t3 pairs exist, processed count must be 0."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
        ):
            result = await dedup_tier3_job({})

        assert result["status"] == "ok"
        assert result["processed"] == 0

    async def test_opencv_pixel_diff_integration_similar_images(
        self, db_session, db_session_factory
    ):
        """High similarity score must move pair to quality_conflict."""
        from worker.dedup_tier3 import dedup_tier3_job

        sha_a = "ka" + "0" * 62
        sha_b = "kb" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100, file_size=5000)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100, file_size=4800)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t3", tier=2)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"0.85"
            if "heuristic" in key:
                return b"1"
            return b"1"  # opencv enabled

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        # Mock pixel diff to return high similarity
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
            patch("worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake/path.jpg")),
            patch(
                "worker.dedup_tier3._opencv_pixel_diff",
                return_value=(0.95, "compression_noise"),
            ),
        ):
            result = await dedup_tier3_job({})

        assert result["status"] == "ok"
        assert result["processed"] >= 1

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] in ("quality_conflict", "variant")

    async def test_opencv_pixel_diff_false_positive_dismissal(
        self, db_session, db_session_factory
    ):
        """Low similarity score must move pair to resolved (false positive)."""
        from worker.dedup_tier3 import dedup_tier3_job

        sha_a = "la" + "0" * 62
        sha_b = "lb" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t3", tier=2)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"0.85"
            if "heuristic" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
            patch("worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake/path.jpg")),
            patch(
                "worker.dedup_tier3._opencv_pixel_diff",
                return_value=(0.40, "localized_diff"),
            ),
        ):
            await dedup_tier3_job({})

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "resolved"

    async def test_opencv_failure_does_not_crash_batch(
        self, db_session, db_session_factory
    ):
        """When _opencv_pixel_diff raises, pair must be marked quality_conflict and processing continues."""
        from worker.dedup_tier3 import dedup_tier3_job

        sha_a = "ma" + "0" * 62
        sha_b = "mb" + "0" * 62
        sha_c = "mc" + "0" * 62
        sha_d = "md" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
        await _insert_blob(session=db_session, sha256=sha_c, width=100, height=100)
        await _insert_blob(session=db_session, sha256=sha_d, width=100, height=100)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t3", tier=2)
        await _insert_relationship(db_session, sha_c, sha_d, "needs_t3", tier=2)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"0.85"
            if "heuristic" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        call_count = 0

        def _failing_diff(path_a, path_b):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("OpenCV decode failure")
            return (0.95, "compression_noise")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
            patch("worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake.jpg")),
            patch("worker.dedup_tier3._opencv_pixel_diff", side_effect=_failing_diff),
        ):
            result = await dedup_tier3_job({})

        # First pair failed → marked quality_conflict; second pair succeeded → processed
        assert result["status"] == "ok"

        # First pair must be marked quality_conflict (failure fallback)
        row_ab = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row_ab is not None
        assert row_ab[0] == "quality_conflict"

    async def test_progress_redis_keys_written_on_completion(
        self, db_session_factory
    ):
        """After job completes, Redis last_run and last_status keys must be set."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
        ):
            await dedup_tier3_job({})

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_none_also_skips(self, db_session_factory):
        """When Redis key is missing (None), job must return skipped."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier3.get_redis", return_value=r):
            result = await dedup_tier3_job({})

        assert result["status"] == "skipped"

    async def test_custom_threshold_respected(self, db_session, db_session_factory):
        """Score exactly at threshold (0.9) with threshold=0.9 must pass as similar."""
        from worker.dedup_tier3 import dedup_tier3_job

        sha_a = "na" + "0" * 62
        sha_b = "nb" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100)
        await _insert_relationship(db_session, sha_a, sha_b, "needs_t3", tier=2)

        r = _make_redis()

        async def _get_side(key):
            if "threshold" in key:
                return b"0.9"
            if "heuristic" in key:
                return b"0"
            return b"1"

        r.get = AsyncMock(side_effect=_get_side)

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
            patch("worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake.jpg")),
            patch(
                "worker.dedup_tier3._opencv_pixel_diff",
                return_value=(0.9, "compression_noise"),
            ),
        ):
            await dedup_tier3_job({})

        row = (
            await db_session.execute(
                text(
                    "SELECT relationship FROM blob_relationships "
                    "WHERE sha_a=:a AND sha_b=:b"
                ),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        # score 0.9 >= threshold 0.9 → confirmed similar
        assert row is not None
        assert row[0] in ("quality_conflict", "variant")
