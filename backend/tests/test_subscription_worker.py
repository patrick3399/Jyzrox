"""Tests for subscription worker functions.

Covers:
- _enqueue_for_subscription: lock guard, source-disabled, credential-required,
  active-job guard, successful enqueue
- check_single_subscription: not-found, success, exception path, disabled subscription
- check_followed_artists: cron gate, no due subs, only-due filter, per-sub exception
  resilience, user_id filter
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub(
    sub_id: int = 1,
    user_id: int = 42,
    url: str = "https://example.com/artist/1",
    source: str = "gallery_dl",
    enabled: bool = True,
    auto_download: bool = True,
    cron_expr: str = "0 */2 * * *",
    next_check_at=None,
):
    """Return a MagicMock representing a Subscription row."""
    sub = MagicMock()
    sub.id = sub_id
    sub.user_id = user_id
    sub.url = url
    sub.source = source
    sub.enabled = enabled
    sub.auto_download = auto_download
    sub.cron_expr = cron_expr
    sub.next_check_at = next_check_at
    sub.name = f"sub-{sub_id}"
    return sub


def _make_mock_session(scalar_result=None):
    """Return a mock async context-manager session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_ctx():
    """Build a minimal worker ctx dict."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.enqueue_job = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.set = MagicMock()
    mock_pipe.delete = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=None)
    redis.pipeline = MagicMock(return_value=mock_pipe)
    return {"redis": redis}


# ---------------------------------------------------------------------------
# TestEnqueueForSubscription
# ---------------------------------------------------------------------------


class TestEnqueueForSubscription:
    """Unit tests for _enqueue_for_subscription()."""

    async def test_lock_not_acquired_returns_skipped(self):
        """If Redis SETNX returns None/False, the function is skipped."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # SETNX failed — another process owns it

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await _enqueue_for_subscription(_make_ctx(), sub)

        assert result["status"] == "skipped"
        assert result["reason"] == "check_in_progress"

    async def test_source_disabled_returns_skipped(self):
        """If the source plugin is disabled, the subscription is skipped and DB updated."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub(source="pixiv")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # lock acquired

        session = _make_mock_session()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("routers.download._check_source_enabled",
                  new_callable=AsyncMock, side_effect=Exception("disabled")),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
        ):
            result = await _enqueue_for_subscription(_make_ctx(), sub)

        assert result["status"] == "skipped"
        assert result["reason"] == "source_disabled"
        session.commit.assert_awaited()

    async def test_credentials_required_but_missing_returns_skipped(self):
        """When credentials are required but absent, subscription is skipped."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub(source="fanbox")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        mock_cfg = MagicMock()
        mock_cfg.credential_requirement = "required"
        mock_cfg.source_id = "fanbox"
        mock_cfg.name = "Fanbox"

        session = _make_mock_session()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("routers.download._check_source_enabled", new_callable=AsyncMock),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=mock_cfg),
            patch("services.credential.get_credential", new_callable=AsyncMock, return_value=None),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
        ):
            result = await _enqueue_for_subscription(_make_ctx(), sub)

        assert result["status"] == "skipped"
        assert result["reason"] == "credentials_required"
        session.commit.assert_awaited()

    async def test_active_job_exists_returns_skipped(self):
        """When an active job already exists for the same URL/user, skip."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        mock_cfg = MagicMock()
        mock_cfg.credential_requirement = "optional"
        mock_cfg.source_id = "gallery_dl"

        existing_job_id = str(uuid.uuid4())

        # First session.execute call (duplicate guard) returns an existing job id;
        # subsequent calls return no existing gallery.
        call_count = [0]

        async def _execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                # Duplicate guard query — returns an active job
                result.scalar_one_or_none = MagicMock(return_value=existing_job_id)
            else:
                result.scalar_one_or_none = MagicMock(return_value=None)
            result.scalars.return_value.all.return_value = []
            return result

        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = _execute_side_effect
        session.add = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("routers.download._check_source_enabled", new_callable=AsyncMock),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=mock_cfg),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
        ):
            result = await _enqueue_for_subscription(_make_ctx(), sub)

        assert result["status"] == "skipped"
        assert result["reason"] == "active_job_exists"

    async def test_successful_enqueue_returns_ok_with_job_id(self):
        """Happy path: no locks, no credential issues, no duplicate — enqueues job."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        mock_cfg = MagicMock()
        mock_cfg.credential_requirement = "optional"
        mock_cfg.source_id = "gallery_dl"

        session = _make_mock_session(scalar_result=None)

        ctx = _make_ctx()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("routers.download._check_source_enabled", new_callable=AsyncMock),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=mock_cfg),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("core.redis_client.publish_job_event", new_callable=AsyncMock),
        ):
            result = await _enqueue_for_subscription(ctx, sub)

        assert result["status"] == "ok"
        assert "job_id" in result
        ctx["redis"].enqueue_job.assert_awaited_once()

    async def test_no_redis_pool_in_ctx_returns_failed(self):
        """If ctx has no redis key, function returns failed immediately."""
        from worker.subscription import _enqueue_for_subscription

        sub = _make_sub()

        result = await _enqueue_for_subscription({}, sub)

        assert result["status"] == "failed"
        assert "no redis" in result["error"]


# ---------------------------------------------------------------------------
# TestCheckSingleSubscription
# ---------------------------------------------------------------------------


class TestCheckSingleSubscription:
    """Unit tests for check_single_subscription()."""

    async def test_subscription_not_found_returns_failed(self):
        """When the subscription ID is absent from DB, returns failed."""
        from worker.subscription import check_single_subscription

        session = _make_mock_session()
        session.get = AsyncMock(return_value=None)

        with (
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("core.redis_client.publish_job_event", new_callable=AsyncMock),
        ):
            result = await check_single_subscription(_make_ctx(), sub_id=999)

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    async def test_successful_check_returns_ok(self):
        """Happy path: subscription found, enqueue succeeds → returns ok."""
        from worker.subscription import check_single_subscription

        sub = _make_sub(sub_id=10)
        session = _make_mock_session()
        session.get = AsyncMock(return_value=sub)

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        mock_cfg = MagicMock()
        mock_cfg.credential_requirement = "optional"
        mock_cfg.source_id = "gallery_dl"

        ctx = _make_ctx()

        with (
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("routers.download._check_source_enabled", new_callable=AsyncMock),
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=mock_cfg),
            patch("core.redis_client.publish_job_event", new_callable=AsyncMock),
        ):
            result = await check_single_subscription(ctx, sub_id=10)

        assert result["status"] == "ok"

    async def test_exception_during_enqueue_updates_status_and_returns_failed(self):
        """If _enqueue_for_subscription raises, last_status is set to 'failed' in DB."""
        from worker.subscription import check_single_subscription

        sub = _make_sub(sub_id=20)
        session = _make_mock_session()
        session.get = AsyncMock(return_value=sub)

        ctx = _make_ctx()

        with (
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("worker.subscription._enqueue_for_subscription",
                  new_callable=AsyncMock,
                  side_effect=RuntimeError("redis unavailable")),
            patch("core.redis_client.publish_job_event", new_callable=AsyncMock),
        ):
            result = await check_single_subscription(ctx, sub_id=20)

        assert result["status"] == "failed"
        assert "redis unavailable" in result["error"]
        # DB should have been updated with the error
        session.commit.assert_awaited()

    async def test_disabled_subscription_still_processed(self):
        """check_single_subscription does not pre-filter disabled subs — that is the
        caller's responsibility; it delegates directly to _enqueue_for_subscription."""
        from worker.subscription import check_single_subscription

        sub = _make_sub(sub_id=30, enabled=False)
        session = _make_mock_session()
        session.get = AsyncMock(return_value=sub)

        ctx = _make_ctx()

        with (
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("worker.subscription._enqueue_for_subscription",
                  new_callable=AsyncMock,
                  return_value={"status": "skipped", "reason": "source_disabled"}),
            patch("core.redis_client.publish_job_event", new_callable=AsyncMock),
        ):
            result = await check_single_subscription(ctx, sub_id=30)

        # It passes through whatever _enqueue_for_subscription returns
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# TestCheckFollowedArtists
# ---------------------------------------------------------------------------


class TestCheckFollowedArtists:
    """Unit tests for check_followed_artists()."""

    async def test_cron_gate_not_reached_returns_skipped(self):
        """When cron gate says not yet due, returns skipped immediately."""
        from worker.subscription import check_followed_artists

        with patch("worker.subscription._cron_should_run",
                   new_callable=AsyncMock, return_value=False):
            result = await check_followed_artists(_make_ctx())

        assert result["status"] == "skipped"

    async def test_no_due_subscriptions_returns_ok_zero(self):
        """When there are no due subscriptions, returns ok with checked=0."""
        from worker.subscription import check_followed_artists

        session = _make_mock_session()
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        ctx = _make_ctx()

        with (
            patch("worker.subscription._cron_should_run",
                  new_callable=AsyncMock, return_value=True),
            patch("worker.subscription._cron_record", new_callable=AsyncMock),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
        ):
            result = await check_followed_artists(ctx)

        assert result["status"] == "ok"
        assert result["checked"] == 0
        assert result["enqueued"] == 0

    async def test_only_due_subscriptions_are_processed(self):
        """The query filters by next_check_at; only due subs are passed to enqueue."""
        from worker.subscription import check_followed_artists

        sub1 = _make_sub(sub_id=1)
        sub2 = _make_sub(sub_id=2)

        session = _make_mock_session()
        due_result = MagicMock()
        due_result.scalars.return_value.all.return_value = [sub1, sub2]
        session.execute = AsyncMock(return_value=due_result)

        ctx = _make_ctx()
        enqueued_ids = []

        async def _fake_enqueue(ctx, sub):
            enqueued_ids.append(sub.id)
            return {"status": "ok", "job_id": str(uuid.uuid4())}

        with (
            patch("worker.subscription._cron_should_run",
                  new_callable=AsyncMock, return_value=True),
            patch("worker.subscription._cron_record", new_callable=AsyncMock),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("worker.subscription._enqueue_for_subscription",
                  side_effect=_fake_enqueue),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await check_followed_artists(ctx)

        assert result["status"] == "ok"
        assert result["checked"] == 2
        assert result["enqueued"] == 2
        assert enqueued_ids == [1, 2]

    async def test_exception_on_one_sub_does_not_stop_others(self):
        """If enqueue raises for one sub, the loop continues with the remaining ones."""
        from worker.subscription import check_followed_artists

        sub1 = _make_sub(sub_id=1)
        sub2 = _make_sub(sub_id=2)

        session = _make_mock_session()
        due_result = MagicMock()
        due_result.scalars.return_value.all.return_value = [sub1, sub2]
        session.execute = AsyncMock(return_value=due_result)

        ctx = _make_ctx()
        processed = []

        async def _flaky_enqueue(ctx, sub):
            processed.append(sub.id)
            if sub.id == 1:
                raise RuntimeError("transient failure")
            return {"status": "ok", "job_id": str(uuid.uuid4())}

        with (
            patch("worker.subscription._cron_should_run",
                  new_callable=AsyncMock, return_value=True),
            patch("worker.subscription._cron_record", new_callable=AsyncMock),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("worker.subscription._enqueue_for_subscription",
                  side_effect=_flaky_enqueue),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await check_followed_artists(ctx)

        # Both subs were attempted even though sub1 raised
        assert 1 in processed
        assert 2 in processed
        # Only sub2 counted as checked (sub1 raised before increment)
        assert result["checked"] == 1
        assert result["enqueued"] == 1

    async def test_user_id_filter_applied_when_provided(self):
        """When user_id is given, cron gate is skipped and only that user's subs load."""
        from worker.subscription import check_followed_artists

        sub = _make_sub(sub_id=5, user_id=7)

        session = _make_mock_session()
        user_result = MagicMock()
        user_result.scalars.return_value.all.return_value = [sub]
        session.execute = AsyncMock(return_value=user_result)

        ctx = _make_ctx()

        with (
            patch("worker.subscription._cron_should_run",
                  new_callable=AsyncMock, return_value=False) as mock_cron,
            patch("worker.subscription._cron_record", new_callable=AsyncMock),
            patch("worker.subscription.AsyncSessionLocal", return_value=session),
            patch("worker.subscription._enqueue_for_subscription",
                  new_callable=AsyncMock,
                  return_value={"status": "ok", "job_id": str(uuid.uuid4())}),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await check_followed_artists(ctx, user_id=7)

        # _cron_should_run must NOT be called when user_id is given
        mock_cron.assert_not_awaited()
        assert result["status"] == "ok"
        assert result["checked"] == 1
