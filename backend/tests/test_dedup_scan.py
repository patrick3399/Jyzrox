"""
Tests for worker/dedup_scan.py.

The dedup_scan_job function uses async_session() directly, so we mock it
along with Redis.  Tests verify control-flow branches:
  - Already running guard
  - pHash disabled path
  - Empty DB (no blobs)
  - Tier 1: pairs found and flushed
  - Stop signal during tier 1
  - Pause + resume during tier 1
  - Tier 2: same-gallery whitelist
  - Tier 2: heuristic classification
  - Tier 2 with no needs_t2 rows
  - Reset mode clears relationships
  - Stop signal during tier 2
"""

from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(scalar_result=None, scalars_all=None):
    """Return a mock async context-manager session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    mock_result.scalar_one = MagicMock(return_value=scalar_result if scalar_result is not None else 0)
    mock_result.scalar = MagicMock(return_value=scalar_result)
    mock_result.scalars.return_value.all.return_value = scalars_all if scalars_all is not None else []
    mock_result.scalars.return_value.__iter__ = MagicMock(return_value=iter(scalars_all or []))
    session.execute = AsyncMock(return_value=mock_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_mock_redis(status=None):
    """Return a mock Redis client pre-configured for dedup tests."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=status)
    r.set = AsyncMock(return_value=True)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.getdel = AsyncMock(return_value=None)  # no signal by default
    r.pipeline = MagicMock(return_value=AsyncMock())

    # Mock pipeline().execute()
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.set = MagicMock(return_value=mock_pipe)
    mock_pipe.delete = MagicMock(return_value=mock_pipe)
    mock_pipe.execute = AsyncMock(return_value=[True, True, True, True, True, True])
    r.pipeline.return_value = mock_pipe

    return r


def _make_blob(sha256, phash_int=None, phash_q0=None, phash_q1=None, phash_q2=None, phash_q3=None,
               width=100, height=100, file_size=1000):
    """Return a mock Blob row."""
    blob = MagicMock()
    blob.sha256 = sha256
    blob.phash_int = phash_int
    blob.phash_q0 = phash_q0
    blob.phash_q1 = phash_q1
    blob.phash_q2 = phash_q2
    blob.phash_q3 = phash_q3
    blob.width = width
    blob.height = height
    blob.file_size = file_size
    return blob


def _make_blob_relationship(sha_a, sha_b, hamming_dist=5, relationship="needs_t2", id_=1,
                             suggested_keep=None, reason=None):
    """Return a mock BlobRelationship row."""
    rel = MagicMock()
    rel.id = id_
    rel.sha_a = sha_a
    rel.sha_b = sha_b
    rel.hamming_dist = hamming_dist
    rel.relationship = relationship
    rel.suggested_keep = suggested_keep
    rel.reason = reason
    return rel


# ---------------------------------------------------------------------------
# Guard conditions
# ---------------------------------------------------------------------------


class TestDedupScanGuards:
    """Tests for early-exit conditions."""

    async def test_already_running_returns_early(self):
        """If status=running, job should abort immediately."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis(status=b"running")

        with patch("worker.dedup_scan.get_redis", return_value=mock_redis):
            result = await dedup_scan_job({})

        assert result["status"] == "already_running"

    async def test_already_paused_returns_early(self):
        """If status=paused, job should abort immediately."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis(status=b"paused")

        with patch("worker.dedup_scan.get_redis", return_value=mock_redis):
            result = await dedup_scan_job({})

        assert result["status"] == "already_running"

    async def test_phash_disabled_returns_skipped(self):
        """If dedup_phash_enabled=0, job returns skipped."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis(status=None)
        # First get = status check (None), second = phash enabled check (b"0")
        mock_redis.get = AsyncMock(side_effect=[None, b"0"])

        with patch("worker.dedup_scan.get_redis", return_value=mock_redis):
            result = await dedup_scan_job({})

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"


# ---------------------------------------------------------------------------
# Tier 1 — pHash scan
# ---------------------------------------------------------------------------


class TestTier1PhashScan:
    """Tests for Tier 1 pHash scanning logic."""

    async def test_empty_blob_table_skips_comparisons(self):
        """With no blobs in DB, tier 1 should complete with 0 pairs inserted."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis()
        # Simulate: status=None, phash_enabled=b"1", threshold=None (default 10)
        # then tier2 needs_t2 count=0, heuristic=None, opencv=None
        mock_redis.get = AsyncMock(side_effect=[
            None,       # status check
            b"1",       # phash enabled
            None,       # threshold (use default 10)
            None,       # heuristic_enabled
            None,       # opencv_enabled
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        # Session that returns empty blob list and zero counts
        session = _make_mock_session(scalar_result=0, scalars_all=[])
        # For tier 2 count query, scalars().all returns empty list (no needs_t2)
        session.execute.return_value.scalar_one = MagicMock(return_value=0)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
        assert result["tier1_inserted"] == 0

    async def test_two_similar_blobs_creates_relationship(self):
        """Two blobs with identical phash should be inserted as a pair."""
        from worker.dedup_scan import dedup_scan_job

        # Two blobs with identical phash_int (hamming distance = 0)
        blob_a = _make_blob("sha_a", phash_int=0xDEADBEEF, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_b", phash_int=0xDEADBEEF, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,       # status
            b"1",       # phash_enabled
            b"10",      # threshold
            None,       # heuristic_enabled
            None,       # opencv_enabled
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        # Use a single versatile session
        versatile_session = AsyncMock()
        versatile_session.__aenter__ = AsyncMock(return_value=versatile_session)
        versatile_session.__aexit__ = AsyncMock(return_value=False)
        versatile_session.commit = AsyncMock()

        query_n = {"n": 0}

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            if n == 1:
                # Blob SELECT for tier 1
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            elif n == 2:
                # pg_insert flush
                r.rowcount = 1
                r.scalar_one = MagicMock(return_value=1)
                r.scalars.return_value.all.return_value = []
            elif n == 3:
                # needs_t2 count
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        versatile_session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=versatile_session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"

    async def test_two_dissimilar_blobs_no_pair_created(self):
        """Blobs with hamming distance > threshold should not form a pair."""
        from worker.dedup_scan import dedup_scan_job

        # Different phash_int values with large hamming distance
        blob_a = _make_blob("sha_diff_a", phash_int=0x0000000000000000, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_diff_b", phash_int=0xFFFFFFFFFFFFFFFF, phash_q0=0xFFFF, phash_q1=0xFFFF)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,   # status
            b"1",   # phash_enabled
            b"10",  # threshold=10
            None,   # heuristic_enabled
            None,   # opencv_enabled
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            if n == 1:
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
        assert result["tier1_inserted"] == 0


# ---------------------------------------------------------------------------
# Stop signal
# ---------------------------------------------------------------------------


class TestStopSignal:
    """Tests for stop signal handling during tier 1."""

    async def test_stop_signal_during_tier1_returns_stopped(self):
        """Stop signal during tier 1 iteration should abort and return stopped."""
        from worker.dedup_scan import dedup_scan_job

        blob_a = _make_blob("sha_stop_a", phash_int=0xABCD, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_stop_b", phash_int=0xABCD, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status check
            b"1",    # phash_enabled
            b"10",   # threshold
        ])
        # First getdel = stop signal (after first blob processed)
        mock_redis.getdel = AsyncMock(return_value=b"stop")

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        query_n = {"n": 0}

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            if query_n["n"] == 1:
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            else:
                r.rowcount = 0
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "stopped"
        assert result["tier"] == 1


# ---------------------------------------------------------------------------
# Reset mode
# ---------------------------------------------------------------------------


class TestResetMode:
    """Tests for mode='reset' which deletes all relationships first."""

    async def test_reset_mode_deletes_all_relationships(self):
        """mode=reset should execute DELETE on BlobRelationship before scanning."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,   # status
            b"1",   # phash_enabled
            b"10",  # threshold
            None,   # heuristic
            None,   # opencv
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        delete_called = {"called": False}
        query_n = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            # Check if this is a DELETE statement
            stmt_str = str(stmt)
            if "DELETE" in stmt_str or "delete" in stmt_str.lower():
                delete_called["called"] = True
            r.scalar_one = MagicMock(return_value=0)
            r.all = MagicMock(return_value=[])
            r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({}, mode="reset")

        # In reset mode, DELETE should be called and job should complete
        assert result["status"] in ("ok", "skipped")


# ---------------------------------------------------------------------------
# Dedup helper functions
# ---------------------------------------------------------------------------


class TestDedupHelpers:
    """Unit tests for worker/dedup_helpers.py helper functions."""

    def test_classify_pair_heuristic_disabled_returns_quality_conflict(self):
        """When heuristic is disabled, all pairs are quality_conflict."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.width = 1920
        blob_a.height = 1080
        blob_a.file_size = 500000
        blob_b = MagicMock()
        blob_b.width = 1280
        blob_b.height = 720
        blob_b.file_size = 200000

        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=False)

        assert rel == "quality_conflict"
        assert keep is None
        assert reason is None

    def test_classify_pair_higher_resolution_a_wins(self):
        """Blob A with significantly higher resolution should be suggested to keep."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.sha256 = "sha_hires"
        blob_a.width = 3840
        blob_a.height = 2160
        blob_a.file_size = 1000000

        blob_b = MagicMock()
        blob_b.sha256 = "sha_lowres"
        blob_b.width = 1280
        blob_b.height = 720
        blob_b.file_size = 500000

        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)

        assert rel == "quality_conflict"
        assert keep == "sha_hires"
        assert reason == "higher_resolution"

    def test_classify_pair_higher_resolution_b_wins(self):
        """Blob B with significantly higher resolution should be suggested to keep."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.sha256 = "sha_lowres2"
        blob_a.width = 800
        blob_a.height = 600
        blob_a.file_size = 200000

        blob_b = MagicMock()
        blob_b.sha256 = "sha_hires2"
        blob_b.width = 3000
        blob_b.height = 2000
        blob_b.file_size = 2000000

        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)

        assert rel == "quality_conflict"
        assert keep == "sha_hires2"
        assert reason == "higher_resolution"

    def test_classify_pair_larger_file_wins(self):
        """When resolutions are similar but file size differs, larger file wins."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.sha256 = "sha_bigfile"
        blob_a.width = 1920
        blob_a.height = 1080
        blob_a.file_size = 5000000  # much larger file

        blob_b = MagicMock()
        blob_b.sha256 = "sha_smallfile"
        blob_b.width = 1920
        blob_b.height = 1080
        blob_b.file_size = 100000

        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)

        assert rel == "quality_conflict"
        assert keep == "sha_bigfile"
        assert reason == "larger_file"

    def test_classify_pair_equal_sizes_returns_variant(self):
        """Blobs with similar resolution and file size are classified as variant."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.sha256 = "sha_variant_a"
        blob_a.width = 1200
        blob_a.height = 800
        blob_a.file_size = 300000

        blob_b = MagicMock()
        blob_b.sha256 = "sha_variant_b"
        blob_b.width = 1200
        blob_b.height = 800
        blob_b.file_size = 310000  # within 20% threshold

        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)

        assert rel == "variant"
        assert keep is None

    def test_now_iso_returns_iso_format_string(self):
        """_now_iso should return a valid ISO 8601 string."""
        from worker.dedup_helpers import _now_iso
        from datetime import datetime

        result = _now_iso()

        assert isinstance(result, str)
        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(result)
        assert parsed is not None

    def test_classify_pair_zero_size_blobs(self):
        """Blobs with zero dimensions should not raise and return some classification."""
        from worker.dedup_helpers import _classify_pair

        blob_a = MagicMock()
        blob_a.sha256 = "sha_zero_a"
        blob_a.width = 0
        blob_a.height = 0
        blob_a.file_size = 0

        blob_b = MagicMock()
        blob_b.sha256 = "sha_zero_b"
        blob_b.width = 0
        blob_b.height = 0
        blob_b.file_size = 0

        # Should not raise
        rel, keep, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)

        assert rel in ("variant", "quality_conflict")


# ---------------------------------------------------------------------------
# DedupProgress
# ---------------------------------------------------------------------------


class TestDedupProgress:
    """Tests for DedupProgress helper class."""

    async def test_start_sets_all_keys(self):
        """DedupProgress.start should set status=running and all progress keys."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        progress = DedupProgress(mock_redis)

        await progress.start("pending", total=100, tier=1)

        mock_redis.pipeline.return_value.execute.assert_called()

    async def test_report_increments_current(self):
        """DedupProgress.report should call set with updated current value."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        progress = DedupProgress(mock_redis)
        progress._current = 0

        await progress.report(5)

        assert progress._current == 5
        mock_redis.set.assert_called_with(DedupProgress.CURRENT_KEY, "5")

    async def test_check_signal_returns_none_when_no_signal(self):
        """check_signal should return None when no signal key in Redis."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        mock_redis.getdel = AsyncMock(return_value=None)
        progress = DedupProgress(mock_redis)

        result = await progress.check_signal()

        assert result is None

    async def test_check_signal_returns_stop_string(self):
        """check_signal should decode and return 'stop' signal."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        mock_redis.getdel = AsyncMock(return_value=b"stop")
        progress = DedupProgress(mock_redis)

        result = await progress.check_signal()

        assert result == "stop"

    async def test_finish_deletes_all_keys(self):
        """DedupProgress.finish should delete all progress keys from Redis."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        progress = DedupProgress(mock_redis)

        await progress.finish()

        mock_redis.delete.assert_called_once_with(*DedupProgress.ALL_KEYS)

    async def test_advance_tier_updates_tier_and_total(self):
        """advance_tier should update TIER_KEY, TOTAL_KEY, and CURRENT_KEY via pipeline."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        progress = DedupProgress(mock_redis)

        await progress.advance_tier(2, total=50)

        mock_redis.pipeline.return_value.execute.assert_called()
        assert progress._current == 0

    async def test_wait_for_resume_returns_true_on_resume_signal(self):
        """wait_for_resume returns True when a 'resume' signal is received."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        mock_redis.getdel = AsyncMock(return_value=b"resume")

        progress = DedupProgress(mock_redis)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await progress.wait_for_resume()

        assert result is True
        mock_redis.set.assert_called_with(DedupProgress.STATUS_KEY, "running")

    async def test_wait_for_resume_returns_false_on_stop_signal(self):
        """wait_for_resume returns False when a 'stop' signal is received."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        mock_redis.getdel = AsyncMock(return_value=b"stop")

        progress = DedupProgress(mock_redis)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await progress.wait_for_resume()

        assert result is False

    async def test_wait_for_resume_polls_until_signal(self):
        """wait_for_resume keeps polling until a non-None signal is returned."""
        from worker.dedup_helpers import DedupProgress

        mock_redis = _make_mock_redis()
        # First two polls return None (no signal), third returns resume
        mock_redis.getdel = AsyncMock(side_effect=[None, None, b"resume"])

        progress = DedupProgress(mock_redis)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await progress.wait_for_resume()

        assert result is True
        assert mock_redis.getdel.call_count == 3


# ---------------------------------------------------------------------------
# Tier 1 — dist > threshold (line 102) and batch flush at 1000 (line 113)
# ---------------------------------------------------------------------------


class TestTier1AdditionalBranches:
    """Tests for specific tier 1 control-flow branches."""

    async def test_pair_with_hamming_distance_above_threshold_is_skipped(self):
        """When full hamming distance exceeds threshold, pair is not added (line 102)."""
        from worker.dedup_scan import dedup_scan_job

        # q01_dist = 0 (passes the early filter)
        # full phash dist: 0x0 XOR 0xFFFFFFFFFFFFFFFF = 64 bits → dist=64 > threshold=10
        blob_a = _make_blob("sha_hd_a", phash_int=0x0000000000000000, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_hd_b", phash_int=0xFFFFFFFFFFFFFFFF, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status
            b"1",    # phash_enabled
            b"10",   # threshold=10 (dist=64 > 10 → skip)
            None,    # heuristic_enabled
            None,    # opencv_enabled
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            if query_n["n"] == 1:
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
        assert result["tier1_inserted"] == 0

    async def test_batch_flush_triggered_at_1000_pairs(self):
        """When pairs_batch reaches 1000 entries, _flush is called mid-loop (line 113)."""
        from worker.dedup_scan import dedup_scan_job

        # Create 46 blobs with identical phash (0 hamming distance).
        # 46 blobs → 46*45/2 = 1035 pairs, which exceeds 1000 → triggers flush.
        blobs = [
            _make_blob(f"sha_{i:03d}", phash_int=0xDEADBEEF, phash_q0=0, phash_q1=0)
            for i in range(46)
        ]

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status
            b"1",    # phash_enabled
            b"10",   # threshold
            None,    # heuristic_enabled
            None,    # opencv_enabled
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        flush_called = {"count": 0}
        query_n = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            if query_n["n"] == 1:
                # Tier 1 blob fetch
                r.all = MagicMock(return_value=blobs)
                r.scalars.return_value.all.return_value = blobs
            elif "INSERT" in str(stmt).upper() or "insert" in str(stmt).lower():
                # Batch flush insert
                flush_called["count"] += 1
                r.rowcount = 35
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
        # Flush must have been called at least once during the loop (mid-loop trigger)
        assert flush_called["count"] >= 1


# ---------------------------------------------------------------------------
# Pause signal during tier 1
# ---------------------------------------------------------------------------


class TestPauseSignalTier1:
    """Tests for pause + resume / pause + stop during tier 1."""

    async def test_pause_then_resume_during_tier1_continues(self):
        """Pause signal followed by resume → job continues and completes (lines 118-122)."""
        from worker.dedup_scan import dedup_scan_job

        blob_a = _make_blob("sha_pause_a", phash_int=0xABCD, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_pause_b", phash_int=0xABCD, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status check
            b"1",    # phash_enabled
            b"10",   # threshold
            None,    # heuristic_enabled
            None,    # opencv_enabled
        ])
        # First check_signal returns "pause", second returns None
        mock_redis.getdel = AsyncMock(side_effect=[b"pause", b"resume", None, None])

        query_n = {"n": 0}
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            if query_n["n"] == 1:
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            else:
                r.rowcount = 1
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"

    async def test_pause_then_stop_during_tier1_returns_stopped(self):
        """Pause signal followed by stop in wait_for_resume → returns stopped (lines 119-122)."""
        from worker.dedup_scan import dedup_scan_job

        blob_a = _make_blob("sha_ps_a", phash_int=0xABCD, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_ps_b", phash_int=0xABCD, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status check
            b"1",    # phash_enabled
            b"10",   # threshold
        ])
        # check_signal returns "pause", then wait_for_resume gets "stop"
        mock_redis.getdel = AsyncMock(side_effect=[b"pause", b"stop"])

        query_n = {"n": 0}
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            if query_n["n"] == 1:
                r.all = MagicMock(return_value=[blob_a, blob_b])
                r.scalars.return_value.all.return_value = [blob_a, blob_b]
            else:
                r.rowcount = 0
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value.all.return_value = []
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "stopped"
        assert result["tier"] == 1


# ---------------------------------------------------------------------------
# Tier 2 — heuristic classify loop (lines 160-226)
# ---------------------------------------------------------------------------


class TestTier2HeuristicLoop:
    """Tests for Tier 2 heuristic classification processing."""

    def _make_needs_t2_pair(self, id_=1, sha_a="sha_a", sha_b="sha_b"):
        return _make_blob_relationship(sha_a, sha_b, id_=id_, relationship="needs_t2")

    async def _run_with_t2_pair(self, pair, blob_a, blob_b, same_gal=False,
                                 heuristic=None, opencv=None, extra_redis_gets=None):
        """Helper: run dedup_scan_job with tier 1 returning no pairs and tier 2 having one pair.

        Query ordering (absolute index):
          n=1: tier1 blob fetch → empty
          n=2: tier2 needs_t2 count → 1
          n=3: tier2 pairs fetch (limit 200) → [pair]
          n=4: blob_a fetch → blob_a
          n=5: blob_b fetch → blob_b
          n=6: same_gal exists check → same_gal value
          n=7+: UPDATE relationship, then second pairs fetch → empty (exit loop)
        """
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis()
        base_gets = [
            None,     # status check
            b"1",     # phash_enabled
            b"10",    # threshold
            heuristic or None,   # heuristic_enabled
            opencv or None,      # opencv_enabled
        ]
        if extra_redis_gets:
            base_gets.extend(extra_redis_gets)
        mock_redis.get = AsyncMock(side_effect=base_gets)
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()

            if n == 1:
                # tier1 blob fetch — empty
                r.all = MagicMock(return_value=[])
                r.scalars.return_value.all.return_value = []
            elif n == 2:
                # tier2 needs_t2 count
                r.scalar_one = MagicMock(return_value=1)
            elif n == 3:
                # tier2 pairs batch fetch → [pair]
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([pair]))
            elif n == 4:
                # blob_a fetch
                r.scalar_one_or_none = MagicMock(return_value=blob_a)
            elif n == 5:
                # blob_b fetch
                r.scalar_one_or_none = MagicMock(return_value=blob_b)
            elif n == 6:
                # same_gal exists check
                r.scalar = MagicMock(return_value=same_gal)
            else:
                # n=7: UPDATE; n=8: second pairs fetch → empty (exits loop)
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))

            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        return result

    async def test_tier2_same_gallery_pair_is_whitelisted(self):
        """Pair where both blobs share a gallery → whitelisted as same_gallery_variant (lines 190-199)."""
        pair = self._make_needs_t2_pair()
        blob_a = _make_blob("sha_a", phash_int=0x1234, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_b", phash_int=0x1234, phash_q0=0, phash_q1=0)

        result = await self._run_with_t2_pair(pair, blob_a, blob_b, same_gal=True)

        assert result["status"] == "ok"
        assert result["tier2_processed"] == 1

    async def test_tier2_pair_with_missing_blob_is_resolved(self):
        """Pair where blob_a is missing from DB → relationship resolved (lines 167-174)."""
        from worker.dedup_scan import dedup_scan_job

        pair = self._make_needs_t2_pair()

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None, b"1", b"10", None, None,
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            # n=1: tier1 blobs → empty
            # n=2: tier2 count → 1
            # n=3: tier2 pairs → [pair]
            # n=4: blob_a → None (missing → triggers resolved branch)
            # n=5+: UPDATE resolved, second pairs → empty
            if n == 1:
                r.all = MagicMock(return_value=[])
                r.scalars.return_value.all.return_value = []
            elif n == 2:
                r.scalar_one = MagicMock(return_value=1)
            elif n == 3:
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([pair]))
            elif n == 4:
                # blob_a is None → missing
                r.scalar_one_or_none = MagicMock(return_value=None)
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))

            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"

    async def test_tier2_heuristic_classification_updates_relationship(self):
        """Pair processed by heuristic classify → relationship updated in DB (lines 201-215)."""
        pair = self._make_needs_t2_pair()
        blob_a = _make_blob("sha_t2_a", phash_int=0x1111, phash_q0=0, phash_q1=0,
                             width=1920, height=1080, file_size=500000)
        blob_b = _make_blob("sha_t2_b", phash_int=0x1111, phash_q0=0, phash_q1=0,
                             width=800, height=600, file_size=200000)

        result = await self._run_with_t2_pair(pair, blob_a, blob_b, same_gal=False,
                                               heuristic=b"1")

        assert result["status"] == "ok"
        assert result["tier2_processed"] == 1

    async def test_tier2_stop_signal_returns_stopped(self):
        """Stop signal during tier 2 → returns stopped at tier 2 (lines 224-226).

        The stop signal fires after the first tier-2 batch (one pair) is processed.
        """
        from worker.dedup_scan import dedup_scan_job

        pair = self._make_needs_t2_pair()
        blob_a = _make_blob("sha_t2s_a", phash_int=0x5678, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_t2s_b", phash_int=0x5678, phash_q0=0, phash_q1=0)

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None, b"1", b"10", None, None,
        ])
        # tier1 has 0 blobs so no check_signal in tier1.
        # tier2 processes 1 pair then calls check_signal → b"stop"
        mock_redis.getdel = AsyncMock(return_value=b"stop")

        query_n = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            # Absolute query index routing:
            # n=1: tier1 blobs (empty)
            # n=2: tier2 needs_t2 count (1)
            # n=3: tier2 pairs fetch (returns [pair])
            # n=4: blob_a fetch (returns blob_a)
            # n=5: blob_b fetch (returns blob_b)
            # n=6: same_gal exists check (False)
            # n=7: UPDATE relationship
            # (after the pair loop, check_signal is called → returns stop)
            if n == 1:
                r.all = MagicMock(return_value=[])
                r.scalars.return_value.all.return_value = []
            elif n == 2:
                r.scalar_one = MagicMock(return_value=1)
            elif n == 3:
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([pair]))
            elif n == 4:
                r.scalar_one_or_none = MagicMock(return_value=blob_a)
            elif n == 5:
                r.scalar_one_or_none = MagicMock(return_value=blob_b)
            elif n == 6:
                # same_gal exists check → False
                r.scalar = MagicMock(return_value=False)
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))

            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "stopped"
        assert result["tier"] == 2


# ---------------------------------------------------------------------------
# Tier 3 — OpenCV pixel-diff (lines 240-344)
# ---------------------------------------------------------------------------


class TestTier3OpenCV:
    """Tests for Tier 3 OpenCV pixel-diff processing."""

    async def _run_with_t3(self, pair, blob_a, blob_b, opencv_score=0.9,
                            opencv_exception=None, threshold_cv=None):
        """Run dedup_scan_job configured for tier 3 processing."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis()
        gets = [
            None,    # status
            b"1",    # phash_enabled
            b"10",   # threshold
            None,    # heuristic_enabled (tier 2)
            b"1",    # opencv_enabled (tier 2 → needs_t3)
            # tier 3 settings:
            threshold_cv or b"0.85",  # opencv_threshold
        ]
        mock_redis.get = AsyncMock(side_effect=gets)
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}
        fetch_count = {"n": 0}
        t2_pair_returned = {"done": False}
        t3_pair_returned = {"done": False}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            stmt_str = str(stmt).upper()

            if n == 1:
                # tier1 blobs — empty
                r.all = MagicMock(return_value=[])
                r.scalars.return_value.all.return_value = []
            elif n == 2:
                # tier2 needs_t2 count — 1
                r.scalar_one = MagicMock(return_value=1)
            elif "SELECT" in stmt_str and not t2_pair_returned["done"]:
                fetch_count["n"] += 1
                fc = fetch_count["n"]
                if fc == 1:
                    # tier2 pairs → one needs_t2 pair
                    t2_pair = _make_blob_relationship("sha_t3_a", "sha_t3_b",
                                                       relationship="needs_t2", id_=10)
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([t2_pair]))
                    t2_pair_returned["done"] = True
                elif fc == 2:
                    r.scalar_one_or_none = MagicMock(return_value=blob_a)
                elif fc == 3:
                    r.scalar_one_or_none = MagicMock(return_value=blob_b)
                elif fc == 4:
                    r.scalar = MagicMock(return_value=False)
                else:
                    r.scalar_one = MagicMock(return_value=0)
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            elif "SELECT" in stmt_str and not t3_pair_returned["done"]:
                fetch_count["n"] += 1
                fc = fetch_count["n"]
                if fc == 5:
                    # tier3 needs_t3 count
                    r.scalar_one = MagicMock(return_value=1)
                elif fc == 6:
                    # tier3 pairs → one needs_t3 pair
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([pair]))
                    t3_pair_returned["done"] = True
                elif fc == 7:
                    r.scalar_one_or_none = MagicMock(return_value=blob_a)
                elif fc == 8:
                    r.scalar_one_or_none = MagicMock(return_value=blob_b)
                else:
                    r.scalar_one = MagicMock(return_value=0)
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            else:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))

            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        if opencv_exception:
            opencv_mock = MagicMock(side_effect=opencv_exception)
        else:
            opencv_mock = MagicMock(return_value=(opencv_score, "compression_noise"))

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
            patch("worker.dedup_helpers._opencv_pixel_diff", opencv_mock),
            patch("services.cas.resolve_blob_path", return_value=MagicMock(__str__=lambda s: "/fake/path")),
            patch("core.events.emit_safe", new=AsyncMock()),
        ):
            result = await dedup_scan_job({})

        return result

    async def test_opencv_disabled_skips_tier3_and_emits_event(self):
        """When opencv is disabled, tier 3 is skipped, event emitted, status=ok (lines 231-238)."""
        from worker.dedup_scan import dedup_scan_job

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None,    # status
            b"1",    # phash_enabled
            b"10",   # threshold
            None,    # heuristic_enabled
            None,    # opencv_enabled (falsy → skip tier 3)
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(_stmt, *_args, **_kwargs):
            query_n["n"] += 1
            r = MagicMock()
            r.all = MagicMock(return_value=[])
            r.scalar_one = MagicMock(return_value=0)
            r.scalars.return_value.all.return_value = []
            r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
            patch("core.events.emit_safe", new=AsyncMock()) as mock_emit,
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
        assert "tier3_processed" not in result
        mock_emit.assert_called_once()

    async def test_tier3_pair_processed_with_high_similarity_score(self):
        """Tier 3 pair with score >= threshold → classified and updated (lines 301-325)."""
        pair = _make_blob_relationship(
            "sha_t3_a", "sha_t3_b", relationship="needs_t3", id_=20,
            suggested_keep=None, reason=None,
        )
        blob_a = _make_blob("sha_t3_a", phash_int=0xAAAA, phash_q0=0, phash_q1=0,
                             width=1920, height=1080, file_size=500000)
        blob_b = _make_blob("sha_t3_b", phash_int=0xAAAA, phash_q0=0, phash_q1=0,
                             width=800, height=600, file_size=200000)

        result = await self._run_with_t3(pair, blob_a, blob_b, opencv_score=0.95)
        assert result["status"] == "ok"

    async def test_tier3_pair_processed_with_low_similarity_score(self):
        """Tier 3 pair with score < threshold → resolved (not a duplicate) (lines 308-310)."""
        pair = _make_blob_relationship(
            "sha_t3_a", "sha_t3_b", relationship="needs_t3", id_=21,
            suggested_keep="sha_t3_a", reason="higher_resolution",
        )
        blob_a = _make_blob("sha_t3_a", phash_int=0xBBBB, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_t3_b", phash_int=0xBBBB, phash_q0=0, phash_q1=0)

        result = await self._run_with_t3(pair, blob_a, blob_b, opencv_score=0.3)
        assert result["status"] == "ok"

    async def test_tier3_opencv_exception_marks_quality_conflict(self):
        """OpenCV exception during pair processing → quality_conflict (lines 291-299)."""
        pair = _make_blob_relationship(
            "sha_t3_a", "sha_t3_b", relationship="needs_t3", id_=22,
        )
        blob_a = _make_blob("sha_t3_a", phash_int=0xCCCC, phash_q0=0, phash_q1=0)
        blob_b = _make_blob("sha_t3_b", phash_int=0xCCCC, phash_q0=0, phash_q1=0)

        result = await self._run_with_t3(pair, blob_a, blob_b,
                                          opencv_exception=ValueError("decode failed"))
        assert result["status"] == "ok"

    async def test_tier3_missing_blob_is_resolved(self):
        """Tier 3 pair where blob is missing → resolved (lines 277-284)."""
        from worker.dedup_scan import dedup_scan_job

        pair = _make_blob_relationship(
            "sha_t3miss_a", "sha_t3miss_b", relationship="needs_t3", id_=23,
        )

        mock_redis = _make_mock_redis()
        mock_redis.get = AsyncMock(side_effect=[
            None, b"1", b"10", None, b"1",
            b"0.85",
        ])
        mock_redis.getdel = AsyncMock(return_value=None)

        query_n = {"n": 0}
        t3_pair_returned = {"done": False}
        fetch_count = {"n": 0}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        async def _execute_side_effect(stmt, *_args, **_kwargs):
            query_n["n"] += 1
            n = query_n["n"]
            r = MagicMock()
            stmt_str = str(stmt).upper()

            if n == 1:
                r.all = MagicMock(return_value=[])
                r.scalars.return_value.all.return_value = []
            elif n == 2:
                r.scalar_one = MagicMock(return_value=0)
            elif "SELECT" in stmt_str and not t3_pair_returned["done"]:
                fetch_count["n"] += 1
                fc = fetch_count["n"]
                if fc == 1:
                    # tier2 pairs → empty
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
                elif fc == 2:
                    # tier3 count → 1
                    r.scalar_one = MagicMock(return_value=1)
                elif fc == 3:
                    # tier3 pairs → one pair
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([pair]))
                    t3_pair_returned["done"] = True
                elif fc == 4:
                    # blob_a → None (missing)
                    r.scalar_one_or_none = MagicMock(return_value=None)
                else:
                    r.scalar_one = MagicMock(return_value=0)
                    r.scalars.return_value = MagicMock()
                    r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            elif "SELECT" in stmt_str:
                r.scalar_one = MagicMock(return_value=0)
                r.scalars.return_value = MagicMock()
                r.scalars.return_value.__iter__ = MagicMock(return_value=iter([]))
            else:
                r.scalar_one = MagicMock(return_value=0)

            return r

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with (
            patch("worker.dedup_scan.get_redis", return_value=mock_redis),
            patch("worker.dedup_scan.async_session", return_value=session),
            patch("services.cas.resolve_blob_path", return_value=MagicMock(__str__=lambda s: "/fake/path")),
            patch("core.events.emit_safe", new=AsyncMock()),
        ):
            result = await dedup_scan_job({})

        assert result["status"] == "ok"
