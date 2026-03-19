"""Tests for subscription group worker functions.

Covers:
- _cron_is_due: never-run, recently run, overdue
- subscription_scheduler: no redis, no due groups, due group dispatched
- check_subscription_group: not found, paused, no eligible subs, happy path
- acquire_lock / release_lock helpers
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_group(
    group_id: int = 1,
    name: str = "Test Group",
    schedule: str = "0 */2 * * *",
    concurrency: int = 2,
    enabled: bool = True,
    priority: int = 5,
    is_system: bool = False,
    status: str = "idle",
    last_run_at=None,
    last_completed_at=None,
):
    g = MagicMock()
    g.id = group_id
    g.name = name
    g.schedule = schedule
    g.concurrency = concurrency
    g.enabled = enabled
    g.priority = priority
    g.is_system = is_system
    g.status = status
    g.last_run_at = last_run_at
    g.last_completed_at = last_completed_at
    return g


def _make_sub(
    sub_id: int = 1,
    group_id: int = 1,
    enabled: bool = True,
    auto_download: bool = True,
):
    s = MagicMock()
    s.id = sub_id
    s.group_id = group_id
    s.enabled = enabled
    s.auto_download = auto_download
    s.url = f"https://example.com/{sub_id}"
    s.source = "gallery_dl"
    s.user_id = 1
    s.name = f"sub-{sub_id}"
    s.cron_expr = "0 */2 * * *"
    return s


def _make_mock_session(get_result=None, scalars_result=None):
    """Return a mock async context-manager session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=MagicMock(id=1) if get_result != "none" else None)
    mock_result.scalars.return_value.all.return_value = scalars_result or []
    session.execute = AsyncMock(return_value=mock_result)
    session.get = AsyncMock(return_value=get_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_ctx():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.enqueue_job = AsyncMock()
    redis.eval = AsyncMock(return_value=1)
    return {"redis": redis}


# ---------------------------------------------------------------------------
# TestCronIsDue
# ---------------------------------------------------------------------------


class TestCronIsDue:
    """Unit tests for _cron_is_due helper."""

    def test_due_when_never_run(self):
        """If last_run is None the schedule is always considered due."""
        from worker.subscription_group import _cron_is_due

        assert _cron_is_due("* * * * *", None) is True

    def test_not_due_when_recently_run(self):
        """A schedule that fires every 6h is not due when last run was just now."""
        from worker.subscription_group import _cron_is_due

        assert _cron_is_due("0 */6 * * *", datetime.now(UTC)) is False

    def test_due_when_last_run_is_old(self):
        """A 6h schedule is due when last run was 7 hours ago."""
        from worker.subscription_group import _cron_is_due

        old = datetime.now(UTC) - timedelta(hours=7)
        assert _cron_is_due("0 */6 * * *", old) is True

    def test_minutely_schedule_due_after_one_minute(self):
        """A * * * * * schedule is due after 65 seconds."""
        from worker.subscription_group import _cron_is_due

        just_over_minute = datetime.now(UTC) - timedelta(seconds=65)
        assert _cron_is_due("* * * * *", just_over_minute) is True

    def test_daily_schedule_not_due_after_one_hour(self):
        """A daily schedule (0 3 * * *) is not due 1 hour after last run."""
        from worker.subscription_group import _cron_is_due

        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        assert _cron_is_due("0 3 * * *", one_hour_ago) is False


# ---------------------------------------------------------------------------
# TestSubscriptionScheduler
# ---------------------------------------------------------------------------


class TestSubscriptionScheduler:
    """Unit tests for subscription_scheduler."""

    async def test_no_redis_returns_failed(self):
        """Empty ctx (no redis key) → immediate failed return."""
        from worker.subscription_group import subscription_scheduler

        result = await subscription_scheduler({})
        assert result["status"] == "failed"
        assert "no redis" in result["error"]

    async def test_no_due_groups_returns_ok_dispatched_zero(self):
        """When no enabled idle groups exist, returns ok with dispatched=0."""
        from worker.subscription_group import subscription_scheduler

        session = _make_mock_session(scalars_result=[])
        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await subscription_scheduler(ctx)

        assert result["status"] == "ok"
        assert result["dispatched"] == 0

    async def test_recently_run_group_not_dispatched(self):
        """A group whose schedule is not yet due is skipped."""
        from worker.subscription_group import subscription_scheduler

        group = _make_group(last_completed_at=datetime.now(UTC))  # just ran

        session = _make_mock_session(scalars_result=[group])
        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await subscription_scheduler(ctx)

        assert result["dispatched"] == 0
        ctx["redis"].enqueue_job.assert_not_awaited()

    async def test_due_group_is_dispatched(self):
        """A group whose schedule is overdue gets claimed and dispatched."""
        from worker.subscription_group import subscription_scheduler

        group = _make_group(last_completed_at=datetime.now(UTC) - timedelta(hours=3))

        call_count = [0]

        async def _execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.all.return_value = [group]
            else:
                result.fetchone = MagicMock(return_value=MagicMock(id=group.id))
            return result

        # subscription_scheduler uses a single AsyncSessionLocal() context
        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = _execute_side_effect
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await subscription_scheduler(ctx)

        assert result["status"] == "ok"
        assert result["dispatched"] == 1
        ctx["redis"].enqueue_job.assert_awaited_once()

    async def test_claim_race_lost_is_not_counted(self):
        """If the atomic claim returns no row (another worker won), dispatched stays 0."""
        from worker.subscription_group import subscription_scheduler

        group = _make_group(last_completed_at=datetime.now(UTC) - timedelta(hours=3))

        call_count = [0]

        async def _execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.all.return_value = [group]
            else:
                result.fetchone = MagicMock(return_value=None)
            return result

        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = _execute_side_effect
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await subscription_scheduler(ctx)

        assert result["dispatched"] == 0
        ctx["redis"].enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestCheckSubscriptionGroup
# ---------------------------------------------------------------------------


class TestCheckSubscriptionGroup:
    """Unit tests for check_subscription_group."""

    async def test_group_not_found_returns_failed(self):
        """When group_id does not exist in DB, returns failed."""
        from worker.subscription_group import check_subscription_group

        session = _make_mock_session()
        session.get = AsyncMock(return_value=None)
        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await check_subscription_group(ctx, group_id=999)

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    async def test_paused_group_returns_skipped(self):
        """A group with status='paused' is skipped immediately."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="paused")
        session = _make_mock_session()
        session.get = AsyncMock(return_value=group)
        ctx = _make_ctx()
        with patch("worker.subscription_group.AsyncSessionLocal", return_value=session):
            result = await check_subscription_group(ctx, group_id=1)

        assert result["status"] == "skipped"
        assert result["reason"] == "paused"

    async def test_no_eligible_subs_returns_ok_checked_zero(self):
        """When group has no enabled+auto_download subs, returns ok with checked=0."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="running")

        # Session 1: get() returns group, execute() returns empty subs
        session1 = AsyncMock()
        session1.commit = AsyncMock()
        session1.get = AsyncMock(return_value=group)
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session1.execute = AsyncMock(return_value=empty_result)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        # Session 2: update status to idle+completed
        session2 = AsyncMock()
        session2.commit = AsyncMock()
        session2.execute = AsyncMock()
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        ctx = _make_ctx()
        with (
            patch("worker.subscription_group.AsyncSessionLocal", side_effect=[session1, session2]),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await check_subscription_group(ctx, group_id=1)

        assert result["status"] == "ok"
        assert result["checked"] == 0
        assert result["enqueued"] == 0

    async def test_happy_path_enqueues_all_eligible_subs(self):
        """All enabled+auto_download subs are enqueued; checked and enqueued counts match."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="running", concurrency=3)
        sub1 = _make_sub(sub_id=1)
        sub2 = _make_sub(sub_id=2)

        # Session 1: load group + query eligible subs
        session1 = AsyncMock()
        session1.commit = AsyncMock()
        session1.get = AsyncMock(return_value=group)
        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub1, sub2]
        session1.execute = AsyncMock(return_value=subs_result)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        # Session 2: mark group complete
        session2 = AsyncMock()
        session2.commit = AsyncMock()
        session2.execute = AsyncMock()
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        async def _fake_enqueue(ctx, sub):
            return {"status": "ok", "job_id": "fake-job"}

        ctx = _make_ctx()
        with (
            patch("worker.subscription_group.AsyncSessionLocal", side_effect=[session1, session2]),
            patch("worker.subscription._enqueue_for_subscription", side_effect=_fake_enqueue),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await check_subscription_group(ctx, group_id=1)

        assert result["status"] == "ok"
        assert result["checked"] == 2
        assert result["enqueued"] == 2
        assert result["errors"] == 0

    async def test_enqueue_failure_increments_errors_not_enqueued(self):
        """When _enqueue_for_subscription raises for a sub, errors is incremented."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="running", concurrency=2)
        sub1 = _make_sub(sub_id=1)

        # Session 1: load group + query subs
        session1 = AsyncMock()
        session1.commit = AsyncMock()
        session1.get = AsyncMock(return_value=group)
        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub1]
        session1.execute = AsyncMock(return_value=subs_result)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        # Session 2: mark group complete
        session2 = AsyncMock()
        session2.commit = AsyncMock()
        session2.execute = AsyncMock()
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        async def _failing_enqueue(ctx, sub):
            raise RuntimeError("network failure")

        ctx = _make_ctx()
        with (
            patch("worker.subscription_group.AsyncSessionLocal", side_effect=[session1, session2]),
            patch("worker.subscription._enqueue_for_subscription", side_effect=_failing_enqueue),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await check_subscription_group(ctx, group_id=1)

        assert result["status"] == "ok"
        assert result["errors"] == 1
        assert result["enqueued"] == 0

    async def test_skipped_sub_does_not_count_as_enqueued(self):
        """When _enqueue_for_subscription returns skipped, enqueued stays 0."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="running", concurrency=2)
        sub1 = _make_sub(sub_id=1)

        # Session 1: load group + query subs
        session1 = AsyncMock()
        session1.commit = AsyncMock()
        session1.get = AsyncMock(return_value=group)
        subs_result = MagicMock()
        subs_result.scalars.return_value.all.return_value = [sub1]
        session1.execute = AsyncMock(return_value=subs_result)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        # Session 2: mark group complete
        session2 = AsyncMock()
        session2.commit = AsyncMock()
        session2.execute = AsyncMock()
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        async def _skip_enqueue(ctx, sub):
            return {"status": "skipped", "reason": "check_in_progress"}

        ctx = _make_ctx()
        with (
            patch("worker.subscription_group.AsyncSessionLocal", side_effect=[session1, session2]),
            patch("worker.subscription._enqueue_for_subscription", side_effect=_skip_enqueue),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await check_subscription_group(ctx, group_id=1)

        assert result["status"] == "ok"
        assert result["checked"] == 1
        assert result["enqueued"] == 0

    async def test_group_status_set_to_idle_after_completion(self):
        """After processing, the group status is reset to idle in the DB."""
        from worker.subscription_group import check_subscription_group

        group = _make_group(status="running", concurrency=2)

        # Session 1: load group + query subs (empty)
        session1 = AsyncMock()
        session1.commit = AsyncMock()
        session1.get = AsyncMock(return_value=group)
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session1.execute = AsyncMock(return_value=empty_result)
        session1.__aenter__ = AsyncMock(return_value=session1)
        session1.__aexit__ = AsyncMock(return_value=False)

        # Session 2: update status to idle+completed
        session2 = AsyncMock()
        session2.commit = AsyncMock()
        session2.execute = AsyncMock()
        session2.__aenter__ = AsyncMock(return_value=session2)
        session2.__aexit__ = AsyncMock(return_value=False)

        ctx = _make_ctx()
        with (
            patch("worker.subscription_group.AsyncSessionLocal", side_effect=[session1, session2]),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await check_subscription_group(ctx, group_id=1)

        # The function must have committed at least once (final status reset)
        assert result["status"] == "ok"
        session2.commit.assert_awaited()


# ---------------------------------------------------------------------------
# TestRenewableLock
# ---------------------------------------------------------------------------


class TestRenewableLock:
    """Unit tests for acquire_lock / release_lock in worker.helpers."""

    async def test_acquire_lock_success_returns_string_value(self):
        """Successful SETNX → returns a non-None string (the lock value)."""
        from worker.helpers import acquire_lock

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)

        lock_val = await acquire_lock(redis, "test:lock", ttl=60)

        assert lock_val is not None
        assert isinstance(lock_val, str)
        redis.set.assert_awaited_once()

    async def test_acquire_lock_uses_nx_and_ex_flags(self):
        """acquire_lock calls redis.set with nx=True and ex=ttl."""
        from worker.helpers import acquire_lock

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)

        await acquire_lock(redis, "my:key", ttl=120)

        call_kwargs = redis.set.call_args.kwargs
        assert call_kwargs.get("nx") is True
        assert call_kwargs.get("ex") == 120

    async def test_acquire_lock_failure_returns_none(self):
        """When SETNX returns None/False (already locked), acquire_lock returns None."""
        from worker.helpers import acquire_lock

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)

        lock_val = await acquire_lock(redis, "test:lock")

        assert lock_val is None

    async def test_acquire_lock_false_response_returns_none(self):
        """When SETNX returns False, acquire_lock also returns None."""
        from worker.helpers import acquire_lock

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=False)

        lock_val = await acquire_lock(redis, "test:lock")

        assert lock_val is None

    async def test_release_lock_success_returns_true(self):
        """Lua script returns 1 (deleted) → release_lock returns True."""
        from worker.helpers import release_lock

        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=1)

        result = await release_lock(redis, "test:lock", "my-lock-value")

        assert result is True
        redis.eval.assert_awaited_once()

    async def test_release_lock_wrong_value_returns_false(self):
        """Lua script returns 0 (value mismatch) → release_lock returns False."""
        from worker.helpers import release_lock

        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=0)

        result = await release_lock(redis, "test:lock", "wrong-value")

        assert result is False

    async def test_release_lock_passes_correct_args_to_eval(self):
        """release_lock calls eval with key count=1, key, and lock_value."""
        from worker.helpers import LOCK_RELEASE_LUA, release_lock

        redis = AsyncMock()
        redis.eval = AsyncMock(return_value=1)

        await release_lock(redis, "my:key", "abc123")

        redis.eval.assert_awaited_once_with(LOCK_RELEASE_LUA, 1, "my:key", "abc123")
