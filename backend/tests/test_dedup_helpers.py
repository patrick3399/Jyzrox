"""
Unit tests for worker.dedup_helpers.

Covers:
- _classify_pair: all heuristic branches and boundary conditions
- _opencv_pixel_diff: happy path, error path, diff-type classification
- _now_iso: basic format validation
- DedupProgress: all Redis-backed async operations
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_blob(sha256: str, width: int | None, height: int | None, file_size: int) -> MagicMock:
    """Return a MagicMock that looks like a Blob ORM row."""
    blob = MagicMock()
    blob.sha256 = sha256
    blob.width = width
    blob.height = height
    blob.file_size = file_size
    return blob


def _make_pipeline() -> MagicMock:
    """Return a synchronous MagicMock pipeline whose chained calls all return self."""
    pipe = MagicMock()
    pipe.set = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=None)
    return pipe


def _make_redis(pipeline: MagicMock | None = None) -> AsyncMock:
    """Return an AsyncMock Redis client with a preconfigured pipeline."""
    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipeline or _make_pipeline())
    redis.set = AsyncMock(return_value=True)
    redis.getdel = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


# ---------------------------------------------------------------------------
# _classify_pair
# ---------------------------------------------------------------------------


class TestClassifyPairHeuristicDisabled:
    """When heuristic_enabled=False the function always returns quality_conflict."""

    def test_classify_pair_heuristic_disabled_returns_quality_conflict(self):
        from worker.dedup_helpers import _classify_pair

        blob_a = _make_blob("aaa", 1920, 1080, 500_000)
        blob_b = _make_blob("bbb", 100, 100, 10_000)
        result = _classify_pair(blob_a, blob_b, heuristic_enabled=False)
        assert result == ("quality_conflict", None, None)

    def test_classify_pair_heuristic_disabled_ignores_resolution(self):
        from worker.dedup_helpers import _classify_pair

        """Even if A has far more pixels the result is still quality_conflict with no winner."""
        blob_a = _make_blob("aaa", 4000, 3000, 1_000_000)
        blob_b = _make_blob("bbb", 10, 10, 100)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=False)
        assert label == "quality_conflict"
        assert winner is None
        assert reason is None


class TestClassifyPairResolutionHeuristic:
    """Resolution-based winner selection (>10 % pixel advantage)."""

    def test_classify_pair_a_wins_higher_resolution(self):
        from worker.dedup_helpers import _classify_pair

        """A has strictly more than 1.10x the pixels of B — A wins."""
        # pixels_a = 1000*1000 = 1_000_000
        # pixels_b =  900* 900 =   810_000
        # ratio = 1_000_000 / 810_000 ≈ 1.235 > 1.10  → A wins
        blob_a = _make_blob("aaa", 1000, 1000, 200_000)
        blob_b = _make_blob("bbb", 900, 900, 200_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "quality_conflict"
        assert winner == "aaa"
        assert reason == "higher_resolution"

    def test_classify_pair_b_wins_higher_resolution(self):
        from worker.dedup_helpers import _classify_pair

        """B has strictly more than 1.10x the pixels of A — B wins."""
        blob_a = _make_blob("aaa", 900, 900, 200_000)
        blob_b = _make_blob("bbb", 1000, 1000, 200_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "quality_conflict"
        assert winner == "bbb"
        assert reason == "higher_resolution"

    def test_classify_pair_boundary_exactly_1_10x_a_wins(self):
        from worker.dedup_helpers import _classify_pair

        """pixels_a == pixels_b * 1.10 is NOT strictly greater, so A does not win on resolution.

        The condition is pixels_a > pixels_b * 1.10 (strict), therefore an exact
        1.10 ratio must NOT trigger the resolution branch.
        """
        # pixels_a = 110, pixels_b = 100  →  110 > 100*1.10 = 110.0  is False
        blob_a = _make_blob("aaa", 11, 10, 200_000)   # 110 pixels
        blob_b = _make_blob("bbb", 10, 10, 200_000)   # 100 pixels
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        # must NOT resolve on higher_resolution
        assert reason != "higher_resolution"

    def test_classify_pair_boundary_just_above_1_10x_a_wins(self):
        from worker.dedup_helpers import _classify_pair

        """pixels_a = pixels_b * 1.10 + 1 — one pixel over the threshold."""
        # pixels_b = 1000, pixels_a = 1101 (1101 > 1000*1.10 = 1100)
        blob_a = _make_blob("aaa", 1101, 1, 200_000)
        blob_b = _make_blob("bbb", 1000, 1, 200_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert winner == "aaa"
        assert reason == "higher_resolution"

    def test_classify_pair_boundary_pixel_diff_below_threshold(self):
        from worker.dedup_helpers import _classify_pair

        """A 5% pixel difference is below the 10% threshold — neither wins on resolution."""
        # pixels_a = 1050, pixels_b = 1000  → ratio 1.05 < 1.10
        blob_a = _make_blob("aaa", 1050, 1, 200_000)
        blob_b = _make_blob("bbb", 1000, 1, 200_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert reason != "higher_resolution"


class TestClassifyPairFileSizeHeuristic:
    """File-size winner selection when pixels are close (≤10 % apart)."""

    def test_classify_pair_a_wins_larger_file(self):
        from worker.dedup_helpers import _classify_pair

        """Equal pixel counts — A has >1.20x the file size of B — A wins."""
        blob_a = _make_blob("aaa", 100, 100, 1_210_000)   # 1_210_000 > 1_000_000 * 1.20
        blob_b = _make_blob("bbb", 100, 100, 1_000_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "quality_conflict"
        assert winner == "aaa"
        assert reason == "larger_file"

    def test_classify_pair_b_wins_larger_file(self):
        from worker.dedup_helpers import _classify_pair

        """Equal pixel counts — B has >1.20x the file size of A — B wins."""
        blob_a = _make_blob("aaa", 100, 100, 1_000_000)
        blob_b = _make_blob("bbb", 100, 100, 1_210_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "quality_conflict"
        assert winner == "bbb"
        assert reason == "larger_file"

    def test_classify_pair_boundary_exactly_1_20x_file_size_no_win(self):
        from worker.dedup_helpers import _classify_pair

        """file_size_a == file_size_b * 1.20 is NOT strictly greater — no winner."""
        # 1_200_000 > 1_000_000 * 1.20 = 1_200_000.0  is False
        blob_a = _make_blob("aaa", 100, 100, 1_200_000)
        blob_b = _make_blob("bbb", 100, 100, 1_000_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert reason != "larger_file"

    def test_classify_pair_boundary_just_above_1_20x_file_size_a_wins(self):
        from worker.dedup_helpers import _classify_pair

        """file_size_a = file_size_b * 1.20 + 1 — A wins."""
        blob_a = _make_blob("aaa", 100, 100, 1_200_001)
        blob_b = _make_blob("bbb", 100, 100, 1_000_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert winner == "aaa"
        assert reason == "larger_file"

    def test_classify_pair_file_size_diff_below_threshold_returns_variant(self):
        from worker.dedup_helpers import _classify_pair

        """5% file-size difference is below the threshold — result is variant."""
        blob_a = _make_blob("aaa", 100, 100, 1_050_000)
        blob_b = _make_blob("bbb", 100, 100, 1_000_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "variant"
        assert winner is None
        assert reason is None


class TestClassifyPairEdgeCases:
    """Edge-case inputs for _classify_pair."""

    def test_classify_pair_zero_dimension_blobs_treated_as_zero_pixels(self):
        from worker.dedup_helpers import _classify_pair

        """Blobs with None width/height are treated as 0 pixels — no resolution winner."""
        blob_a = _make_blob("aaa", None, None, 1_000_000)
        blob_b = _make_blob("bbb", None, None, 1_000_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        # 0 pixels each; file sizes equal → variant
        assert label == "variant"

    def test_classify_pair_one_zero_dimension_blob(self):
        from worker.dedup_helpers import _classify_pair

        """One blob with None dimensions and one with a real resolution."""
        # pixels_b = 1000*1000 = 1_000_000; pixels_a = 0
        # 1_000_000 > 0 * 1.10 = 0  → True  → B wins
        blob_a = _make_blob("aaa", None, None, 500_000)
        blob_b = _make_blob("bbb", 1000, 1000, 500_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert winner == "bbb"
        assert reason == "higher_resolution"

    def test_classify_pair_exact_equal_blobs_returns_variant(self):
        from worker.dedup_helpers import _classify_pair, _opencv_pixel_diff

        """Identical pixel count and file size → variant with no winner."""
        blob_a = _make_blob("aaa", 1920, 1080, 800_000)
        blob_b = _make_blob("bbb", 1920, 1080, 800_000)
        label, winner, reason = _classify_pair(blob_a, blob_b, heuristic_enabled=True)
        assert label == "variant"
        assert winner is None
        assert reason is None


# ---------------------------------------------------------------------------
# _opencv_pixel_diff
# ---------------------------------------------------------------------------


def _build_cv2_mock(mean_diff: float, std_diff: float) -> tuple[MagicMock, MagicMock]:
    """Build a cv2 mock and a numpy mock returning the given statistics."""
    mock_img = MagicMock(name="img")
    mock_diff_arr = MagicMock(name="diff_arr")

    mock_cv2 = MagicMock(name="cv2")
    mock_cv2.IMREAD_GRAYSCALE = 0
    mock_cv2.INTER_AREA = 0
    mock_cv2.imread.return_value = mock_img
    mock_cv2.resize.return_value = mock_img
    mock_cv2.absdiff.return_value = mock_diff_arr

    mock_np = MagicMock(name="numpy")
    mock_float32 = MagicMock(name="float32")
    mock_np.float32 = mock_float32
    mock_diff_arr.astype.return_value = mock_diff_arr
    mock_np.mean.return_value = mean_diff
    mock_np.std.return_value = std_diff

    return mock_cv2, mock_np


class TestOpencvPixelDiff:
    """Tests for _opencv_pixel_diff (cv2 and numpy are patched at import time)."""

    def test_opencv_pixel_diff_identical_images_returns_compression_noise(self):
        from worker.dedup_helpers import _opencv_pixel_diff

        """mean_diff < 10 → similarity near 1.0, diff_type 'compression_noise'."""
        mean_diff = 3.0
        std_diff = 2.0   # 2.0 <= 3.0 * 1.5 → also noise branch
        mock_cv2, mock_np = _build_cv2_mock(mean_diff, std_diff)

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            similarity, diff_type = _opencv_pixel_diff("/a.jpg", "/b.jpg")

        expected_similarity = 1.0 - (mean_diff / 255.0)
        assert abs(similarity - expected_similarity) < 1e-9
        assert diff_type == "compression_noise"

    def test_opencv_pixel_diff_different_images_returns_localized_diff(self):
        from worker.dedup_helpers import _opencv_pixel_diff

        """mean_diff >= 10 and std_diff > mean_diff*1.5 → 'localized_diff'."""
        mean_diff = 20.0
        std_diff = 40.0   # 40.0 > 20.0 * 1.5 = 30.0
        mock_cv2, mock_np = _build_cv2_mock(mean_diff, std_diff)

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            similarity, diff_type = _opencv_pixel_diff("/a.jpg", "/b.jpg")

        assert diff_type == "localized_diff"
        assert similarity < 1.0

    def test_opencv_pixel_diff_img_a_none_raises_value_error(self):
        from worker.dedup_helpers import _opencv_pixel_diff

        """cv2.imread returns None for path_a → ValueError('decode failed')."""
        mock_cv2, mock_np = _build_cv2_mock(0.0, 0.0)
        mock_cv2.imread.side_effect = [None, MagicMock()]  # first call → None

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            with pytest.raises(ValueError, match="decode failed"):
                _opencv_pixel_diff("/missing.jpg", "/b.jpg")

    def test_opencv_pixel_diff_img_b_none_raises_value_error(self):
        from worker.dedup_helpers import _opencv_pixel_diff

        """cv2.imread returns None for path_b → ValueError('decode failed')."""
        mock_cv2, mock_np = _build_cv2_mock(0.0, 0.0)
        mock_cv2.imread.side_effect = [MagicMock(), None]  # second call → None

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            with pytest.raises(ValueError, match="decode failed"):
                _opencv_pixel_diff("/a.jpg", "/missing.jpg")

    def test_opencv_pixel_diff_high_mean_low_std_compression_noise(self):
        from worker.dedup_helpers import _opencv_pixel_diff

        """mean_diff >= 10 but std_diff <= mean_diff*1.5 → still 'compression_noise'."""
        mean_diff = 15.0
        std_diff = 10.0   # 10.0 <= 15.0 * 1.5 = 22.5
        mock_cv2, mock_np = _build_cv2_mock(mean_diff, std_diff)

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            similarity, diff_type = _opencv_pixel_diff("/a.jpg", "/b.jpg")

        assert diff_type == "compression_noise"

    def test_opencv_pixel_diff_similarity_formula(self):
        from worker.dedup_helpers import _opencv_pixel_diff, _now_iso

        """similarity == 1.0 - (mean_diff / 255.0) for any valid mean_diff."""
        mean_diff = 51.0   # → similarity = 1.0 - 0.2 = 0.8
        std_diff = 5.0
        mock_cv2, mock_np = _build_cv2_mock(mean_diff, std_diff)

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": mock_np}):
            similarity, _ = _opencv_pixel_diff("/a.jpg", "/b.jpg")

        assert abs(similarity - 0.8) < 1e-9


# ---------------------------------------------------------------------------
# _now_iso
# ---------------------------------------------------------------------------


class TestNowIso:
    """Tests for the _now_iso helper."""

    def test_now_iso_returns_string(self):
        from worker.dedup_helpers import _now_iso

        result = _now_iso()
        assert isinstance(result, str)

    def test_now_iso_contains_utc_offset_or_z(self):
        from worker.dedup_helpers import _now_iso

        """ISO format with UTC must include '+00:00' or end with 'Z'."""
        result = _now_iso()
        assert "+00:00" in result or result.endswith("Z")

    def test_now_iso_is_parseable_datetime(self):
        from worker.dedup_helpers import _now_iso

        """The returned string must be parseable by datetime.fromisoformat."""
        from datetime import datetime

        result = _now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.year >= 2024


# ---------------------------------------------------------------------------
# DedupProgress
# ---------------------------------------------------------------------------


class TestDedupProgressStart:
    """Tests for DedupProgress.start()."""

    async def test_start_sets_running_status_via_pipeline(self):
        """start() must call pipeline.set with STATUS_KEY='running'."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)

        await dp.start("full", 500, 1)

        set_calls = [call.args for call in pipe.set.call_args_list]
        assert (DedupProgress.STATUS_KEY, "running") in set_calls

    async def test_start_sets_mode_and_total_and_tier(self):
        """start() must record mode, total, and tier in Redis via the pipeline."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)

        await dp.start("incremental", 200, 2)

        set_calls = [call.args for call in pipe.set.call_args_list]
        assert (DedupProgress.MODE_KEY, "incremental") in set_calls
        assert (DedupProgress.TOTAL_KEY, "200") in set_calls
        assert (DedupProgress.TIER_KEY, "2") in set_calls

    async def test_start_resets_internal_current_to_zero(self):
        """After start(), the in-memory _current counter must be 0."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)
        dp._current = 99  # simulate dirty state

        await dp.start("full", 100, 1)

        assert dp._current == 0

    async def test_start_deletes_signal_key(self):
        """start() must delete the SIGNAL_KEY to clear any leftover signal."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)

        await dp.start("full", 100, 1)

        pipe.delete.assert_called_once_with(DedupProgress.SIGNAL_KEY)


class TestDedupProgressAdvanceTier:
    """Tests for DedupProgress.advance_tier()."""

    async def test_advance_tier_updates_tier_and_total(self):
        """advance_tier() must update TIER_KEY and TOTAL_KEY via pipeline."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)

        await dp.advance_tier(2, 300)

        set_calls = [call.args for call in pipe.set.call_args_list]
        assert (DedupProgress.TIER_KEY, "2") in set_calls
        assert (DedupProgress.TOTAL_KEY, "300") in set_calls

    async def test_advance_tier_resets_current_to_zero(self):
        """advance_tier() must reset CURRENT_KEY to '0' and _current to 0."""
        from worker.dedup_helpers import DedupProgress

        pipe = _make_pipeline()
        redis = _make_redis(pipe)
        dp = DedupProgress(redis)
        dp._current = 42

        await dp.advance_tier(2, 100)

        set_calls = [call.args for call in pipe.set.call_args_list]
        assert (DedupProgress.CURRENT_KEY, "0") in set_calls
        assert dp._current == 0


class TestDedupProgressReport:
    """Tests for DedupProgress.report()."""

    async def test_report_increments_current_by_one(self):
        """report() with no argument increments _current by 1."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        dp = DedupProgress(redis)

        await dp.report()

        assert dp._current == 1
        redis.set.assert_awaited_once_with(DedupProgress.CURRENT_KEY, "1")

    async def test_report_increments_by_custom_amount(self):
        """report(5) increments _current by 5."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        dp = DedupProgress(redis)

        await dp.report(5)

        assert dp._current == 5
        redis.set.assert_awaited_once_with(DedupProgress.CURRENT_KEY, "5")

    async def test_report_accumulates_across_calls(self):
        """Multiple report() calls accumulate the counter correctly."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        dp = DedupProgress(redis)

        await dp.report(3)
        await dp.report(7)

        assert dp._current == 10


class TestDedupProgressCheckSignal:
    """Tests for DedupProgress.check_signal()."""

    async def test_check_signal_returns_none_when_no_signal(self):
        """getdel returning None → check_signal returns None."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        redis.getdel = AsyncMock(return_value=None)
        dp = DedupProgress(redis)

        result = await dp.check_signal()

        assert result is None

    async def test_check_signal_decodes_bytes_signal(self):
        """getdel returning bytes → check_signal decodes and returns string."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        redis.getdel = AsyncMock(return_value=b"pause")
        dp = DedupProgress(redis)

        result = await dp.check_signal()

        assert result == "pause"
        assert isinstance(result, str)

    async def test_check_signal_returns_string_signal_unchanged(self):
        """getdel returning a plain str → check_signal returns it as-is."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        redis.getdel = AsyncMock(return_value="stop")
        dp = DedupProgress(redis)

        result = await dp.check_signal()

        assert result == "stop"


class TestDedupProgressWaitForResume:
    """Tests for DedupProgress.wait_for_resume()."""

    async def test_wait_for_resume_returns_true_on_resume_signal(self):
        """A 'resume' signal causes wait_for_resume to set status=running and return True."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        redis.getdel = AsyncMock(return_value=b"resume")

        dp = DedupProgress(redis)

        with patch("worker.dedup_helpers.asyncio.sleep", new_callable=AsyncMock):
            result = await dp.wait_for_resume()

        assert result is True
        redis.set.assert_any_await(DedupProgress.STATUS_KEY, "running")

    async def test_wait_for_resume_returns_false_on_stop_signal(self):
        """A 'stop' signal causes wait_for_resume to return False without setting running."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        redis.getdel = AsyncMock(return_value=b"stop")

        dp = DedupProgress(redis)

        with patch("worker.dedup_helpers.asyncio.sleep", new_callable=AsyncMock):
            result = await dp.wait_for_resume()

        assert result is False

    async def test_wait_for_resume_sets_paused_status_before_polling(self):
        """wait_for_resume must set STATUS_KEY='paused' before the polling loop."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        # Return None once (loop continues), then 'stop' to exit
        redis.getdel = AsyncMock(side_effect=[None, b"stop"])

        dp = DedupProgress(redis)
        paused_call_index = None
        call_order = []

        original_set = redis.set

        async def tracking_set(key, value):
            call_order.append(("set", key, value))
            return await original_set(key, value)

        redis.set = tracking_set

        with patch("worker.dedup_helpers.asyncio.sleep", new_callable=AsyncMock):
            await dp.wait_for_resume()

        assert ("set", DedupProgress.STATUS_KEY, "paused") in call_order
        # paused must appear before running (which won't exist for stop signal)
        assert call_order[0] == ("set", DedupProgress.STATUS_KEY, "paused")

    async def test_wait_for_resume_skips_none_signals_and_continues(self):
        """None signals are skipped; polling continues until a real signal arrives."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        # Three None responses then resume
        redis.getdel = AsyncMock(side_effect=[None, None, None, b"resume"])

        dp = DedupProgress(redis)

        with patch("worker.dedup_helpers.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await dp.wait_for_resume()

        assert result is True
        assert mock_sleep.await_count == 4


class TestDedupProgressFinish:
    """Tests for DedupProgress.finish()."""

    async def test_finish_deletes_all_keys(self):
        """finish() must call redis.delete with all keys in ALL_KEYS."""
        from worker.dedup_helpers import DedupProgress

        redis = _make_redis()
        dp = DedupProgress(redis)

        await dp.finish()

        redis.delete.assert_awaited_once_with(*DedupProgress.ALL_KEYS)

    async def test_finish_all_keys_contains_expected_keys(self):
        """ALL_KEYS must include every individual key constant."""
        from worker.dedup_helpers import DedupProgress

        expected = {
            DedupProgress.STATUS_KEY,
            DedupProgress.SIGNAL_KEY,
            DedupProgress.CURRENT_KEY,
            DedupProgress.TOTAL_KEY,
            DedupProgress.TIER_KEY,
            DedupProgress.MODE_KEY,
        }
        assert set(DedupProgress.ALL_KEYS) == expected
