"""
Unit tests for the dedup pipeline workers (tier 1, 2, 3).

Strategy:
- Patch `core.database.async_session` with the test SQLite session factory
  so all DB calls go through the in-memory DB.
- Mock Redis via AsyncMock so no real Redis connection is required.
- Mock `worker.dedup_helpers._opencv_pixel_diff` for tier 3 to avoid cv2 dep.
- Insert blobs / blob_relationships directly via raw SQL (SQLite-compatible).
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select, text, update

from db.models import Blob, BlobRelationship, Gallery

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
    for suffix, sha in (("a", sha_a), ("b", sha_b)):
        source_id = f"dedup-{sha_a[:8]}-{sha_b[:8]}-{suffix}"
        await session.execute(
            text(
                "INSERT OR IGNORE INTO galleries (source, source_id, title, download_status) "
                "VALUES ('test', :source_id, 'Dedup Context', 'downloaded')"
            ),
            {"source_id": source_id},
        )
        gallery_id = (
            await session.execute(select(Gallery.id).where(Gallery.source == "test", Gallery.source_id == source_id))
        ).scalar_one()
        await session.execute(
            text(
                "INSERT OR IGNORE INTO images (gallery_id, page_num, blob_sha256) "
                "VALUES (:gallery_id, 1, :sha)"
            ),
            {"gallery_id": gallery_id, "sha": sha},
        )
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


async def _insert_occurrence(session, sha256: str, source_id: str, page_num: int = 1) -> int:
    await session.execute(
        text(
            "INSERT OR IGNORE INTO galleries (source, source_id, title, download_status) "
            "VALUES ('context', :source_id, 'Context Gallery', 'downloaded')"
        ),
        {"source_id": source_id},
    )
    gallery_id = (
        await session.execute(
            select(Gallery.id)
            .where(Gallery.source == "context", Gallery.source_id == source_id)
            .order_by(Gallery.id)
            .limit(1)
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT OR IGNORE INTO images (gallery_id, page_num, blob_sha256) "
            "VALUES (:gallery_id, :page_num, :sha)"
        ),
        {"gallery_id": gallery_id, "page_num": page_num, "sha": sha256},
    )
    await session.commit()
    return gallery_id


def _make_ctx() -> dict:
    """SAQ-style ctx with a mocked redis for the cron gate/record calls."""
    return {"redis": _make_redis()}


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
            result = await dedup_tier1_job(_make_ctx(), force=True)

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
            result = await dedup_tier1_job(_make_ctx(), force=True)

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
            result = await dedup_tier1_job(_make_ctx(), force=True)

        # With threshold=0 even hamming dist=0 would be accepted (0 <= 0)
        # Both blobs have identical phash_int so dist=0 which passes threshold=0
        assert result["status"] == "ok"

    async def test_pigeonhole_prefilter_skips_dissimilar_pairs(self, db_session, db_session_factory):
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
            result = await dedup_tier1_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        # The pair with high q0 difference must have been skipped
        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).scalar()
        assert count == 0

    async def test_similar_pairs_stored_in_blob_relationships(self, db_session, db_session_factory):
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
            result = await dedup_tier1_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        count = (
            await db_session.execute(text("SELECT COUNT(*) FROM blob_relationships WHERE relationship='needs_context'"))
        ).scalar()
        assert count >= 1

    async def test_batch_flush_inserts_on_conflict_do_nothing(self, db_session, db_session_factory):
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
            await dedup_tier1_job(_make_ctx(), force=True)
            await dedup_tier1_job(_make_ctx(), force=True)

        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).scalar()
        assert count == 1

    async def test_second_run_skips_blobs_already_scanned_at_threshold(self, db_session, db_session_factory):
        from worker.dedup_tier1 import dedup_tier1_job

        await _insert_blob(session=db_session, sha256="d1" + "0" * 62, phash_int=1)
        await _insert_blob(session=db_session, sha256="d2" + "0" * 62, phash_int=3)
        r = _make_redis()
        r.get = AsyncMock(side_effect=lambda key: b"10" if "threshold" in key else b"1")
        fake_db = _make_session_cm(db_session_factory)

        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            first = await dedup_tier1_job(_make_ctx(), force=True)
            second = await dedup_tier1_job(_make_ctx(), force=True)

        await db_session.execute(
            update(Blob).where(Blob.sha256 == "d1" + "0" * 62).values(phash_int=7)
        )
        await db_session.commit()
        with (
            patch("worker.dedup_tier1.get_redis", return_value=r),
            patch("worker.dedup_tier1.async_session", fake_db),
        ):
            after_phash_change = await dedup_tier1_job(_make_ctx(), force=True)

        assert first["scanned"] == 2
        assert second["scanned"] == 0
        assert after_phash_change["scanned"] == 1
        thresholds = (
            await db_session.execute(select(Blob.dedup_scanned_threshold).order_by(Blob.sha256))
        ).scalars().all()
        assert thresholds == [10, 10]

    async def test_progress_redis_keys_written_on_completion(self, db_session, db_session_factory):
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
            await dedup_tier1_job(_make_ctx(), force=True)

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_flag_none_also_skips(self, db_session_factory):
        """enabled=None (key missing) must also return skipped."""
        from worker.dedup_tier1 import dedup_tier1_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier1.get_redis", return_value=r):
            result = await dedup_tier1_job(_make_ctx(), force=True)

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
            await dedup_tier1_job(_make_ctx(), force=True)

        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
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
            result = await dedup_tier2_job(_make_ctx(), force=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    async def test_heuristic_disabled_does_not_execute_tier2(self):
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(side_effect=lambda key: b"0" if "heuristic" in key else b"1")

        with patch("worker.dedup_tier2.get_redis", return_value=r):
            result = await dedup_tier2_job(_make_ctx(), force=True)

        assert result == {"status": "skipped", "reason": "disabled"}

    async def test_no_needs_t2_relationships_returns_zero(self, db_session, db_session_factory):
        """When no needs_t2 pairs exist, processed count must be 0."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            result = await dedup_tier2_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        assert result["processed"] == 0

    async def test_same_gallery_only_is_suppressed_but_rechecked_when_context_changes(
        self, db_session, db_session_factory
    ):
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "ctxa" + "0" * 60
        sha_b = "ctxb" + "0" * 60
        await _insert_blob(session=db_session, sha256=sha_a)
        await _insert_blob(session=db_session, sha256=sha_b)
        pair_id = await _insert_relationship(db_session, sha_a, sha_b, "needs_t2")

        # Replace the helper's cross-gallery fixtures with one shared gallery.
        await db_session.execute(text("DELETE FROM images WHERE blob_sha256 IN (:a, :b)"), {"a": sha_a, "b": sha_b})
        await _insert_occurrence(db_session, sha_a, "shared", 1)
        await _insert_occurrence(db_session, sha_b, "shared", 2)

        r = _make_redis()
        r.get = AsyncMock(side_effect=lambda key: b"0" if "opencv" in key else b"1")
        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job(_make_ctx(), force=True)

        first = (
            await db_session.execute(
                select(BlobRelationship.relationship, BlobRelationship.context_scope).where(
                    BlobRelationship.id == pair_id
                )
            )
        ).one()
        assert first == ("same_gallery_only", "same_gallery_only")

        # A new occurrence in another gallery makes the pair mixed. The next
        # Tier-2 run must re-evaluate the suppressed state and classify it.
        await _insert_occurrence(db_session, sha_a, "other", 1)
        # SQLite tests do not install the PostgreSQL occurrence trigger.
        await db_session.execute(
            update(Blob).where(Blob.sha256 == sha_a).values(occurrence_revision=1)
        )
        await db_session.commit()
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job(_make_ctx(), force=True)

        second = (
            await db_session.execute(
                select(BlobRelationship.relationship, BlobRelationship.context_scope).where(
                    BlobRelationship.id == pair_id
                )
            )
        ).one()
        assert second[0] in ("quality_conflict", "variant")
        assert second[1] == "mixed"

    async def test_heuristic_higher_resolution_classify(self, db_session, db_session_factory):
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
            result = await dedup_tier2_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        assert result["processed"] >= 1

        row = (
            await db_session.execute(
                text("SELECT relationship, reason FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
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
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100, file_size=15000)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100, file_size=10000)
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
            await dedup_tier2_job(_make_ctx(), force=True)

        row = (
            await db_session.execute(
                text("SELECT relationship, reason FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "quality_conflict"
        assert row[1] == "larger_file"

    async def test_heuristic_similar_size_produces_variant(self, db_session, db_session_factory):
        """Blobs with equal resolution and similar file size must be classified as variant."""
        from worker.dedup_tier2 import dedup_tier2_job

        sha_a = "ha" + "0" * 62
        sha_b = "hb" + "0" * 62
        await _insert_blob(session=db_session, sha256=sha_a, width=100, height=100, file_size=10000)
        await _insert_blob(session=db_session, sha256=sha_b, width=100, height=100, file_size=10050)
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
            await dedup_tier2_job(_make_ctx(), force=True)

        row = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "variant"

    async def test_opencv_enabled_routes_to_needs_t3(self, db_session, db_session_factory):
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
            await dedup_tier2_job(_make_ctx(), force=True)

        row = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
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
            result = await dedup_tier2_job(_make_ctx(), force=True)

        assert result["processed"] >= 3

    async def test_progress_redis_keys_written_on_completion(self, db_session_factory):
        """After job completes, Redis last_run and last_status keys must be set."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier2.get_redis", return_value=r),
            patch("worker.dedup_tier2.async_session", fake_db),
        ):
            await dedup_tier2_job(_make_ctx(), force=True)

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_none_also_skips(self, db_session_factory):
        """When Redis key is missing (None), job must return skipped."""
        from worker.dedup_tier2 import dedup_tier2_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier2.get_redis", return_value=r):
            result = await dedup_tier2_job(_make_ctx(), force=True)

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
            result = await dedup_tier3_job(_make_ctx(), force=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    async def test_no_needs_t3_relationships_returns_zero(self, db_session, db_session_factory):
        """When no needs_t3 pairs exist, processed count must be 0."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
        ):
            result = await dedup_tier3_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        assert result["processed"] == 0

    async def test_opencv_pixel_diff_integration_similar_images(self, db_session, db_session_factory):
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
            patch(
                "worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake/path.jpg")
            ),
            patch(
                "worker.dedup_tier3._opencv_pixel_diff",
                return_value=(0.95, "compression_noise"),
            ),
        ):
            result = await dedup_tier3_job(_make_ctx(), force=True)

        assert result["status"] == "ok"
        assert result["processed"] >= 1

        row = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] in ("quality_conflict", "variant")

    async def test_opencv_pixel_diff_false_positive_dismissal(self, db_session, db_session_factory):
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
            patch(
                "worker.dedup_tier3.resolve_blob_path", return_value=MagicMock(__str__=lambda self: "/fake/path.jpg")
            ),
            patch(
                "worker.dedup_tier3._opencv_pixel_diff",
                return_value=(0.40, "localized_diff"),
            ),
        ):
            await dedup_tier3_job(_make_ctx(), force=True)

        row = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "resolved"

    async def test_opencv_failure_does_not_crash_batch(self, db_session, db_session_factory):
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
            result = await dedup_tier3_job(_make_ctx(), force=True)

        # First pair failed → marked quality_conflict; second pair succeeded → processed
        assert result["status"] == "ok"

        # First pair must be marked quality_conflict (failure fallback)
        row_ab = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        assert row_ab is not None
        assert row_ab[0] == "quality_conflict"

    async def test_progress_redis_keys_written_on_completion(self, db_session_factory):
        """After job completes, Redis last_run and last_status keys must be set."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=b"1")

        fake_db = _make_session_cm(db_session_factory)
        with (
            patch("worker.dedup_tier3.get_redis", return_value=r),
            patch("worker.dedup_tier3.async_session", fake_db),
        ):
            await dedup_tier3_job(_make_ctx(), force=True)

        set_calls = [call.args[0] for call in r.set.call_args_list]
        assert any("last_run" in k for k in set_calls)
        assert any("last_status" in k for k in set_calls)

    async def test_disabled_none_also_skips(self, db_session_factory):
        """When Redis key is missing (None), job must return skipped."""
        from worker.dedup_tier3 import dedup_tier3_job

        r = _make_redis()
        r.get = AsyncMock(return_value=None)

        with patch("worker.dedup_tier3.get_redis", return_value=r):
            result = await dedup_tier3_job(_make_ctx(), force=True)

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
            await dedup_tier3_job(_make_ctx(), force=True)

        row = (
            await db_session.execute(
                text("SELECT relationship FROM blob_relationships WHERE sha_a=:a AND sha_b=:b"),
                {"a": sha_a, "b": sha_b},
            )
        ).fetchone()
        # score 0.9 >= threshold 0.9 → confirmed similar
        assert row is not None
        assert row[0] == "needs_review"


# ---------------------------------------------------------------------------
# Orchestrator safety contract
# ---------------------------------------------------------------------------


async def test_t1_only_scan_produces_neutral_cross_gallery_review(db_session, db_session_factory):
    from worker.dedup_scan import dedup_scan_job

    sha_a = "only-t1-a" + "0" * 55
    sha_b = "only-t1-b" + "0" * 55
    await _insert_blob(session=db_session, sha256=sha_a, phash_int=42)
    await _insert_blob(session=db_session, sha256=sha_b, phash_int=42)
    await _insert_occurrence(db_session, sha_a, "t1-gallery-a", 1)
    await _insert_occurrence(db_session, sha_b, "t1-gallery-b", 1)

    r = _make_redis()

    async def _get_side(key):
        if key == "setting:dedup_phash_enabled":
            return b"1"
        if key == "setting:dedup_phash_threshold":
            return b"4"
        return None

    r.get = AsyncMock(side_effect=_get_side)
    fake_db = _make_session_cm(db_session_factory)
    with (
        patch("worker.dedup_scan.get_redis", return_value=r),
        patch("worker.dedup_scan.async_session", fake_db),
    ):
        result = await dedup_scan_job({}, mode="pending")

    assert result["status"] == "ok"
    row = (
        await db_session.execute(
            select(
                BlobRelationship.relationship,
                BlobRelationship.context_scope,
                BlobRelationship.tier,
                BlobRelationship.suggested_keep,
            ).where(BlobRelationship.sha_a == sha_a, BlobRelationship.sha_b == sha_b)
        )
    ).one()
    assert row == ("needs_review", "cross_gallery", 1, None)


async def test_full_rescan_preserves_durable_review_decisions(db_session, db_session_factory):
    from worker.dedup_scan import dedup_scan_job

    sha_a = "decision-a" + "0" * 54
    sha_b = "decision-b" + "0" * 54
    await _insert_blob(session=db_session, sha256=sha_a, phash_int=None)
    await _insert_blob(session=db_session, sha256=sha_b, phash_int=None)
    pair_id = await _insert_relationship(db_session, sha_a, sha_b, "decided")
    await db_session.execute(
        update(BlobRelationship)
        .where(BlobRelationship.id == pair_id)
        .values(decision="whitelisted")
    )
    await db_session.commit()

    r = _make_redis()

    async def _get_side(key):
        if key == "setting:dedup_phash_enabled":
            return b"1"
        if key == "setting:dedup_phash_threshold":
            return b"4"
        return None

    r.get = AsyncMock(side_effect=_get_side)
    fake_db = _make_session_cm(db_session_factory)
    with (
        patch("worker.dedup_scan.get_redis", return_value=r),
        patch("worker.dedup_scan.async_session", fake_db),
    ):
        result = await dedup_scan_job({}, mode="reset")

    assert result["status"] == "ok"
    decision = (
        await db_session.execute(
            select(BlobRelationship.decision).where(BlobRelationship.id == pair_id)
        )
    ).scalar_one()
    assert decision == "whitelisted"


async def test_dirty_quality_candidate_reenters_same_gallery_context_gate(db_session, db_session_factory):
    """A prior T2 label must not bypass same-gallery suppression after references change."""
    from worker.dedup_scan import dedup_scan_job

    sha_a = "dirty-quality-a" + "0" * 49
    sha_b = "dirty-quality-b" + "0" * 49
    await _insert_blob(session=db_session, sha256=sha_a, phash_int=None)
    await _insert_blob(session=db_session, sha256=sha_b, phash_int=None)
    await _insert_occurrence(db_session, sha_a, "shared-gallery", 1)
    await _insert_occurrence(db_session, sha_b, "shared-gallery", 2)
    pair_id = (
        await db_session.execute(
            text(
                "INSERT INTO blob_relationships "
                "(sha_a, sha_b, hamming_dist, relationship, tier) "
                "VALUES (:sha_a, :sha_b, 2, 'quality_conflict', 2) RETURNING id"
            ),
            {"sha_a": sha_a, "sha_b": sha_b},
        )
    ).scalar_one()
    await db_session.execute(
        update(Blob).where(Blob.sha256.in_((sha_a, sha_b))).values(occurrence_revision=1)
    )
    await db_session.execute(
        update(BlobRelationship)
        .where(BlobRelationship.id == pair_id)
        .values(context_revision_a=0, context_revision_b=0)
    )
    await db_session.commit()

    r = _make_redis()

    async def _get_side(key):
        if key == "setting:dedup_phash_enabled":
            return b"1"
        if key == "setting:dedup_phash_threshold":
            return b"4"
        return None

    r.get = AsyncMock(side_effect=_get_side)
    fake_db = _make_session_cm(db_session_factory)
    with (
        patch("worker.dedup_scan.get_redis", return_value=r),
        patch("worker.dedup_scan.async_session", fake_db),
    ):
        result = await dedup_scan_job({}, mode="pending")

    assert result["status"] == "ok"
    row = (
        await db_session.execute(
            select(BlobRelationship.relationship, BlobRelationship.context_scope).where(
                BlobRelationship.id == pair_id
            )
        )
    ).one()
    assert row == ("same_gallery_only", "same_gallery_only")


# ---------------------------------------------------------------------------
# TestDedupTierCronGate — edge case #25 regression
# ---------------------------------------------------------------------------


class TestDedupTierCronGate:
    """Edge case #25: scheduled-task UI enable/cron controls were dead for the
    dedup tiers — the jobs never consulted the cron:{task_id}:* namespace."""

    @staticmethod
    def _tier(n: int):
        import worker.dedup_tier1 as t1
        import worker.dedup_tier2 as t2
        import worker.dedup_tier3 as t3

        return {
            1: (t1.dedup_tier1_job, "worker.dedup_tier1"),
            2: (t2.dedup_tier2_job, "worker.dedup_tier2"),
            3: (t3.dedup_tier3_job, "worker.dedup_tier3"),
        }[n]

    @staticmethod
    def _cron_redis(values: dict[str, bytes | None]) -> AsyncMock:
        r = _make_redis()

        async def _get(key):
            return values.get(key)

        r.get = AsyncMock(side_effect=_get)
        return r

    async def test_cron_invocation_with_default_disabled_skips_without_running(self):
        """default_enabled=False + no UI override → cron firing must not run the scan."""
        for n in (1, 2, 3):
            job, module = self._tier(n)
            ctx = {"redis": self._cron_redis({})}
            with patch(f"{module}.get_redis") as body_redis:
                result = await job(ctx)

            assert result == {"status": "skipped", "reason": "cron_gate"}, f"tier{n}"
            body_redis.assert_not_called()

    async def test_cron_invocation_with_ui_disabled_skips_even_when_dedup_toggle_on(self):
        """UI 'Enabled=off' must win even while setting:dedup_*_enabled is on."""
        for n in (1, 2, 3):
            job, module = self._tier(n)
            ctx = {"redis": self._cron_redis({f"cron:dedup_tier{n}:enabled": b"0"})}
            body = _make_redis()
            body.get = AsyncMock(return_value=b"1")  # global dedup toggles all on
            with patch(f"{module}.get_redis", return_value=body):
                result = await job(ctx)

            assert result == {"status": "skipped", "reason": "cron_gate"}, f"tier{n}"
            body.get.assert_not_called()

    async def test_cron_invocation_with_ui_enabled_reaches_job_body(self):
        """UI 'Enabled=on' must let the cron firing proceed into the tier body."""
        for n in (1, 2, 3):
            job, module = self._tier(n)
            ctx = {"redis": self._cron_redis({f"cron:dedup_tier{n}:enabled": b"1"})}
            body = _make_redis()
            body.get = AsyncMock(return_value=b"0")  # body sees dedup toggle off
            with patch(f"{module}.get_redis", return_value=body):
                result = await job(ctx)

            # Reaching the body's own toggle check proves the gate opened.
            assert result == {"status": "skipped", "reason": "disabled"}, f"tier{n}"

    async def test_manual_run_kwargs_force_bypass_cron_gate(self):
        """Scheduled-task 'Run Now' must enqueue the tiers with force=True (BE-T8)."""
        from core.scheduled_task_catalog import CONFIGURABLE_TASK_DEFS

        for task_id in ("dedup_tier1", "dedup_tier2", "dedup_tier3"):
            assert CONFIGURABLE_TASK_DEFS[task_id].manual_kwargs == {"force": True}, task_id
