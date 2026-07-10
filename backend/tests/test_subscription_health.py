"""DL-007: consecutive-failure tracking + backoff for subscriptions.

Chronic failures (expired cookies, dead accounts, broken URLs) previously
failed silently on every scheduler pass — no alert, no backoff, a check
every cycle forever.
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


def _make_redis(count_value=None):
    r = AsyncMock()
    r.get = AsyncMock(return_value=count_value)
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock()
    r.delete = AsyncMock()
    return r


# ---------------------------------------------------------------------------
# record_check_result
# ---------------------------------------------------------------------------


class TestRecordCheckResult:
    @pytest.mark.asyncio
    async def test_failed_increments_counter(self):
        from services.subscription_health import record_check_result

        redis = _make_redis()
        redis.incr = AsyncMock(return_value=2)
        with patch("core.redis_client.get_redis", return_value=redis):
            count = await record_check_result(7, "failed")

        assert count == 2
        redis.incr.assert_awaited_once()
        redis.expire.assert_awaited()

    @pytest.mark.asyncio
    async def test_done_resets_counter(self):
        from services.subscription_health import record_check_result

        redis = _make_redis()
        with patch("core.redis_client.get_redis", return_value=redis):
            count = await record_check_result(7, "done")

        assert count == 0
        redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_resets_counter(self):
        from services.subscription_health import record_check_result

        redis = _make_redis()
        with patch("core.redis_client.get_redis", return_value=redis):
            count = await record_check_result(7, "partial")

        assert count == 0
        redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancelled_leaves_counter_untouched(self):
        """User cancellation is not a source failure."""
        from services.subscription_health import record_check_result

        redis = _make_redis(count_value=b"2")
        with patch("core.redis_client.get_redis", return_value=redis):
            count = await record_check_result(7, "cancelled")

        assert count == 2
        redis.incr.assert_not_awaited()
        redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_emitted_exactly_when_threshold_crossed(self):
        from services.subscription_health import FAILURE_ALERT_THRESHOLD, record_check_result

        redis = _make_redis()
        redis.incr = AsyncMock(return_value=FAILURE_ALERT_THRESHOLD)
        with (
            patch("core.redis_client.get_redis", return_value=redis),
            patch("core.events.emit_safe", new_callable=AsyncMock) as mock_emit,
        ):
            await record_check_result(7, "failed")

        mock_emit.assert_awaited_once()
        assert mock_emit.call_args.kwargs.get("resource_id") == 7

    @pytest.mark.asyncio
    async def test_no_event_below_or_beyond_threshold(self):
        from services.subscription_health import FAILURE_ALERT_THRESHOLD, record_check_result

        for count in (1, FAILURE_ALERT_THRESHOLD - 1, FAILURE_ALERT_THRESHOLD + 1):
            redis = _make_redis()
            redis.incr = AsyncMock(return_value=count)
            with (
                patch("core.redis_client.get_redis", return_value=redis),
                patch("core.events.emit_safe", new_callable=AsyncMock) as mock_emit,
            ):
                await record_check_result(7, "failed")
            mock_emit.assert_not_awaited()


# ---------------------------------------------------------------------------
# backoff_seconds / should_backoff
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_no_backoff_below_threshold(self):
        from services.subscription_health import FAILURE_ALERT_THRESHOLD, backoff_seconds

        for n in range(FAILURE_ALERT_THRESHOLD):
            assert backoff_seconds(n) == 0

    def test_backoff_doubles_and_caps(self):
        from services.subscription_health import (
            BACKOFF_BASE_S,
            BACKOFF_MAX_S,
            FAILURE_ALERT_THRESHOLD,
            backoff_seconds,
        )

        assert backoff_seconds(FAILURE_ALERT_THRESHOLD) == BACKOFF_BASE_S
        assert backoff_seconds(FAILURE_ALERT_THRESHOLD + 1) == BACKOFF_BASE_S * 2
        assert backoff_seconds(FAILURE_ALERT_THRESHOLD + 20) == BACKOFF_MAX_S

    @pytest.mark.asyncio
    async def test_should_backoff_true_within_window(self):
        from services.subscription_health import FAILURE_ALERT_THRESHOLD, should_backoff

        redis = _make_redis(count_value=str(FAILURE_ALERT_THRESHOLD).encode())
        recent = datetime.now(UTC) - timedelta(seconds=10)
        with patch("core.redis_client.get_redis", return_value=redis):
            skip, failures = await should_backoff(7, recent)

        assert skip is True
        assert failures == FAILURE_ALERT_THRESHOLD

    @pytest.mark.asyncio
    async def test_should_backoff_false_after_window_elapsed(self):
        from services.subscription_health import (
            BACKOFF_BASE_S,
            FAILURE_ALERT_THRESHOLD,
            should_backoff,
        )

        redis = _make_redis(count_value=str(FAILURE_ALERT_THRESHOLD).encode())
        old = datetime.now(UTC) - timedelta(seconds=BACKOFF_BASE_S + 60)
        with patch("core.redis_client.get_redis", return_value=redis):
            skip, _ = await should_backoff(7, old)

        assert skip is False

    @pytest.mark.asyncio
    async def test_should_backoff_fails_open_when_redis_unavailable(self):
        """Health tracking must never block subscription checks — a Redis
        error means no backoff, not a crashed check."""
        from services.subscription_health import should_backoff

        redis = _make_redis()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("core.redis_client.get_redis", return_value=redis):
            skip, failures = await should_backoff(7, datetime.now(UTC))

        assert skip is False
        assert failures == 0

    @pytest.mark.asyncio
    async def test_record_fails_open_when_redis_unavailable(self):
        from services.subscription_health import record_check_result

        redis = _make_redis()
        redis.incr = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("core.redis_client.get_redis", return_value=redis):
            count = await record_check_result(7, "failed")

        assert count == 0

    @pytest.mark.asyncio
    async def test_should_backoff_false_with_no_failures(self):
        from services.subscription_health import should_backoff

        redis = _make_redis(count_value=None)
        with patch("core.redis_client.get_redis", return_value=redis):
            skip, failures = await should_backoff(7, datetime.now(UTC))

        assert skip is False
        assert failures == 0


# ---------------------------------------------------------------------------
# Wiring: _set_subscription_result records the terminal status
# ---------------------------------------------------------------------------


def _make_session_capture(subscription_id=7):
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_job = MagicMock()
    fake_job.subscription_id = subscription_id
    fake_session.get = AsyncMock(return_value=fake_job)
    fake_session.execute = AsyncMock(return_value=MagicMock())
    fake_session.commit = AsyncMock()
    return fake_session


class TestDownloadResultWiring:
    @pytest.mark.asyncio
    async def test_failed_result_records_failure(self, monkeypatch):
        import core.database as cdb
        from worker import download as dl_mod

        fake_session = _make_session_capture(subscription_id=7)
        monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

        with patch("services.subscription_health.record_check_result", new_callable=AsyncMock) as mock_record:
            await dl_mod._set_subscription_result(str(uuid.uuid4()), "failed", "boom")

        mock_record.assert_awaited_once_with(7, "failed")

    @pytest.mark.asyncio
    async def test_done_result_records_success(self, monkeypatch):
        import core.database as cdb
        from worker import download as dl_mod

        fake_session = _make_session_capture(subscription_id=7)
        monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

        with patch("services.subscription_health.record_check_result", new_callable=AsyncMock) as mock_record:
            await dl_mod._set_subscription_result(str(uuid.uuid4()), "done")

        mock_record.assert_awaited_once_with(7, "done")


# ---------------------------------------------------------------------------
# Wiring: _enqueue_for_subscription backoff gate
# ---------------------------------------------------------------------------


def _make_ctx():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return {"redis": redis}


def _make_sub(sub_id=1):
    sub = MagicMock()
    sub.id = sub_id
    sub.user_id = 42
    sub.url = "https://example.com/artist/1"
    sub.source = "gallery_dl"
    sub.name = f"sub-{sub_id}"
    sub.cron_expr = "0 */2 * * *"
    sub.group_id = None
    sub.last_checked_at = datetime.now(UTC)
    sub.last_success_at = None
    return sub


class TestEnqueueBackoffGate:
    @pytest.mark.asyncio
    async def test_auto_check_skipped_during_backoff(self):
        """A sub with enough consecutive failures is skipped by automatic
        checks while inside its backoff window."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "services.subscription_health.should_backoff",
                new_callable=AsyncMock,
                return_value=(True, 4),
            ),
        ):
            result = await _enqueue_for_subscription(_make_ctx(), sub)

        assert result["status"] == "skipped"
        assert result["reason"] == "failure_backoff"

    @pytest.mark.asyncio
    async def test_manual_check_bypasses_backoff(self):
        """check_single_subscription (user-triggered) must not be blocked by
        the backoff window — the user explicitly asked for a check."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch(
                "services.subscription_health.should_backoff",
                new_callable=AsyncMock,
                return_value=(True, 4),
            ) as mock_backoff,
            patch(
                "services.source_health.is_source_enabled",
                new_callable=AsyncMock,
                return_value=False,  # stop the flow right after the gate
            ),
            patch("worker.subscription.AsyncSessionLocal"),
        ):
            result = await _enqueue_for_subscription(_make_ctx(), sub, manual=True)

        mock_backoff.assert_not_awaited()
        assert result["reason"] != "failure_backoff"
