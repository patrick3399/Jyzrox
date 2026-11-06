"""Durable subscription pause (ADR 0030): service, halt handling, durability gates."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text

from db.models import DownloadJob, Subscription
from services.download_pause import PAUSE_KEY_TTL, PauseConflict, pause_job, pause_key
from services.subscription_pause import (
    check_lock_key,
    halt_subscription_for_job,
    pause_subscription,
    rate_limit_cooldown,
    resume_due_rate_limited,
    resume_subscription,
)


class _ctx:
    """Async context manager yielding the shared test session (stands in for AsyncSessionLocal())."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
async def _clean_rows(db_session):
    """worker.startup() leaves a connection open on the shared-cache SQLite DB, so rows would
    outlive the test and leak into later tests (UNIQUE subscriptions, extra jobs)."""
    yield
    await db_session.rollback()
    await db_session.execute(text("DELETE FROM download_jobs"))
    await db_session.execute(text("DELETE FROM subscriptions"))
    await db_session.commit()


@pytest.fixture(autouse=True)
def _redis_for_services(mock_redis):
    """Both pause services bind get_redis at import time; point them at the mock."""
    with (
        patch("services.subscription_pause.get_redis", return_value=mock_redis),
        patch("services.download_pause.get_redis", return_value=mock_redis),
    ):
        yield


async def _sub(db, user_id=1):
    await db.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (:i, :u, 'x', 'admin')"),
        {"i": user_id, "u": f"u{user_id}"},
    )
    r = await db.execute(
        text(
            "INSERT INTO subscriptions (user_id, url, name, source, enabled, auto_download, cron_expr) "
            "VALUES (:u, :url, 'n', 'fanbox', 1, 1, '0 */2 * * *') RETURNING id"
        ),
        {"u": user_id, "url": f"https://www.fanbox.cc/@{uuid.uuid4().hex[:6]}"},
    )
    sid = r.scalar_one()
    await db.commit()
    return sid


async def _job(db, sub_id, status, ticket, *, token=None, stop=False, retry_count=0):
    jid = uuid.uuid4()
    db.add(
        DownloadJob(
            id=jid,
            url=f"https://www.fanbox.cc/@a/posts/{ticket}",
            canonical_url=f"https://www.fanbox.cc/@a/posts/{ticket}",
            source="fanbox",
            status=status,
            progress={},
            options={},
            mode="subscription_initial",
            user_id=1,
            subscription_id=sub_id,
            admission_key="fanbox",
            admission_ticket=ticket,
            admission_token=token,
            retry_count=retry_count,
            stop_requested_at=datetime.now(UTC) if stop else None,
        )
    )
    await db.commit()
    return jid


async def _mark_paused(db, sid, reason="manual", until=None):
    await db.execute(
        text(
            "UPDATE subscriptions SET paused_at = CURRENT_TIMESTAMP, paused_reason = :r, paused_until = :u "
            "WHERE id = :i"
        ),
        {"r": reason, "u": until, "i": sid},
    )
    await db.commit()


def test_check_lock_key_and_pause_key_formats_are_stable():
    assert check_lock_key(7) == "subscription:check_lock:7"
    assert pause_key("abc") == "download:pause:abc"
    assert PAUSE_KEY_TTL == 86400


async def test_pause_job_terminal_status_raises_pause_conflict(db_session, mock_redis):
    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "done", 1)
    job = await db_session.get(DownloadJob, jid)
    with pytest.raises(PauseConflict):
        await pause_job(db_session, job)


async def test_pause_subscription_pauses_queued_and_running_but_not_stop_requested_jobs(db_session, mock_redis):
    sid = await _sub(db_session)
    q = await _job(db_session, sid, "queued", 1)
    r = await _job(db_session, sid, "running", 2, token=uuid.uuid4())
    s = await _job(db_session, sid, "queued", 3, stop=True)
    d = await _job(db_session, sid, "done", 4)

    out = await pause_subscription(db_session, sid, reason="manual")

    rows = {j.id: j.status for j in (await db_session.execute(select(DownloadJob))).scalars()}
    assert (rows[q], rows[r], rows[s], rows[d]) == ("paused", "paused", "queued", "done")
    assert out["paused_jobs"] == 2
    mock_redis.set.assert_any_await(f"download:pause:{r}", b"1", ex=86400)
    sub = await db_session.get(Subscription, sid)
    assert sub.paused_at is not None and sub.paused_reason == "manual"


async def test_rate_limit_halt_does_not_override_manual_pause(db_session, mock_redis):
    sid = await _sub(db_session)
    await pause_subscription(db_session, sid, reason="manual")
    out = await pause_subscription(
        db_session, sid, reason="rate_limited", until=datetime.now(UTC) + timedelta(minutes=30)
    )
    sub = await db_session.get(Subscription, sid)
    await db_session.refresh(sub)
    assert out["applied"] is False
    assert sub.paused_reason == "manual" and sub.paused_until is None


async def test_auth_halt_does_not_override_manual_pause_but_replaces_rate_limit_pause(db_session, mock_redis):
    manual = await _sub(db_session)
    limited = await _sub(db_session)
    await pause_subscription(db_session, manual, reason="manual")
    await pause_subscription(
        db_session, limited, reason="rate_limited", until=datetime.now(UTC) + timedelta(minutes=30)
    )

    assert (await pause_subscription(db_session, manual, reason="auth"))["applied"] is False
    assert (await pause_subscription(db_session, limited, reason="auth"))["applied"] is True

    reasons = {s.id: s.paused_reason for s in (await db_session.execute(select(Subscription))).scalars()}
    await db_session.commit()
    assert (reasons[manual], reasons[limited]) == ("manual", "auth")


async def test_pause_subscription_unknown_reason_raises_value_error(db_session, mock_redis):
    sid = await _sub(db_session)
    with pytest.raises(ValueError):
        await pause_subscription(db_session, sid, reason="bogus")


async def test_resume_subscription_requeues_paused_jobs_in_original_ticket_order(db_session, mock_redis):
    sid = await _sub(db_session)
    late = await _job(db_session, sid, "paused", 20)
    early = await _job(db_session, sid, "paused", 10)
    stopped = await _job(db_session, sid, "paused", 5, stop=True)
    await _mark_paused(db_session, sid)
    order = []
    new_tickets = itertools.count(1000)

    with (
        patch(
            "services.download_pause.enqueue_download_job",
            AsyncMock(side_effect=lambda job, key: order.append(job.id)),
        ),
        patch("services.download_pause.next_admission_ticket", AsyncMock(side_effect=lambda db: next(new_tickets))),
        patch("services.download_pause.resolve_admission_key", AsyncMock(return_value="fanbox")),
    ):
        out = await resume_subscription(db_session, sid)

    assert order == [early, late]
    assert out["resumed_jobs"] == 2
    statuses = {j.id: j for j in (await db_session.execute(select(DownloadJob))).scalars()}
    assert statuses[stopped].status == "paused"
    # New FIFO tickets follow the original order, so the queue drains oldest-first.
    assert statuses[early].admission_ticket < statuses[late].admission_ticket
    sub = await db_session.get(Subscription, sid)
    await db_session.refresh(sub)
    assert sub.paused_at is None and sub.paused_reason is None


async def test_auto_resume_only_reason_rate_limited_skips_manual_pause(db_session, mock_redis):
    sid = await _sub(db_session)
    await pause_subscription(db_session, sid, reason="manual")
    out = await resume_subscription(db_session, sid, only_reason="rate_limited")
    assert out["status"] == "skipped"
    sub = await db_session.get(Subscription, sid)
    await db_session.refresh(sub)
    assert sub.paused_reason == "manual"


def test_rate_limit_cooldown_doubles_and_caps_and_honours_retry_after():
    assert rate_limit_cooldown(0, None) == timedelta(minutes=30)
    assert rate_limit_cooldown(1, None) == timedelta(minutes=60)
    assert rate_limit_cooldown(10, None) == timedelta(hours=6)
    assert rate_limit_cooldown(0, 7200) == timedelta(hours=2)
    assert rate_limit_cooldown(0, 10 * 86400) == timedelta(hours=24)


# ---------------------------------------------------------------------------
# Task 9: halt handling + scheduler auto-resume
# ---------------------------------------------------------------------------


async def test_halt_subscription_for_job_pauses_job_and_subscription_without_consuming_retry(db_session, mock_redis):
    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "running", 1, token=uuid.uuid4())
    other = await _job(db_session, sid, "queued", 2)
    with patch("services.subscription_pause.AsyncSessionLocal", return_value=_ctx(db_session)):
        assert await halt_subscription_for_job(str(jid), "rate_limited", None) is True
    job = await db_session.get(DownloadJob, jid)
    await db_session.refresh(job)
    assert (job.status, job.retry_count) == ("paused", 0)
    assert (await db_session.get(DownloadJob, other)).status == "paused"
    sub = await db_session.get(Subscription, sid)
    await db_session.refresh(sub)
    assert sub.paused_reason == "rate_limited" and sub.paused_until is not None and sub.halt_count == 1


async def test_halt_subscription_for_job_auth_reason_has_no_auto_resume_time(db_session, mock_redis):
    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "running", 1, token=uuid.uuid4())
    with patch("services.subscription_pause.AsyncSessionLocal", return_value=_ctx(db_session)):
        assert await halt_subscription_for_job(str(jid), "auth", None) is True
    sub = await db_session.get(Subscription, sid)
    await db_session.refresh(sub)
    assert sub.paused_reason == "auth" and sub.paused_until is None


async def test_halt_subscription_for_job_without_subscription_returns_false(db_session, mock_redis):
    jid = uuid.uuid4()
    db_session.add(
        DownloadJob(
            id=jid,
            url="https://www.fanbox.cc/@a/posts/1",
            canonical_url="https://www.fanbox.cc/@a/posts/1",
            source="fanbox",
            status="running",
            progress={},
            options={},
            user_id=None,
        )
    )
    await db_session.commit()
    with patch("services.subscription_pause.AsyncSessionLocal", return_value=_ctx(db_session)):
        assert await halt_subscription_for_job(str(jid), "rate_limited", None) is False
    assert (await db_session.get(DownloadJob, jid)).status == "running"


async def test_resume_due_rate_limited_resumes_only_expired_rate_limit_pauses(db_session, mock_redis):
    due = await _sub(db_session)
    later = await _sub(db_session)
    manual = await _sub(db_session)
    past, future = datetime.now(UTC) - timedelta(minutes=1), datetime.now(UTC) + timedelta(hours=1)
    for sid, reason, until in ((due, "rate_limited", past), (later, "rate_limited", future), (manual, "manual", None)):
        await _mark_paused(db_session, sid, reason, until)
    with patch("services.subscription_pause.AsyncSessionLocal", return_value=_ctx(db_session)):
        assert await resume_due_rate_limited() == 1
    reasons = {s.id: s.paused_reason for s in (await db_session.execute(select(Subscription))).scalars()}
    await db_session.commit()
    assert (reasons[due], reasons[later], reasons[manual]) == (None, "rate_limited", "manual")


# ---------------------------------------------------------------------------
# Task 7: durability — retry cron and startup recovery
# ---------------------------------------------------------------------------


async def _run_retry_cron(db_session, mock_redis, enq):
    from worker.retry import retry_failed_downloads_job

    with (
        patch("worker.retry._cron_should_run", AsyncMock(return_value=True)),
        patch("worker.retry._cron_record", AsyncMock()),
        patch("worker.retry.AsyncSessionLocal", return_value=_ctx(db_session)),
        patch("worker.retry.enqueue_download_job", enq),
        patch("worker.retry.next_admission_ticket", AsyncMock(return_value=9999)),
        patch("worker.retry.resolve_admission_key", AsyncMock(return_value="fanbox")),
    ):
        return await retry_failed_downloads_job({"redis": mock_redis})


async def test_retry_cron_does_not_retry_failed_jobs_of_paused_subscription(db_session, mock_redis):
    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "failed", 1)
    await _mark_paused(db_session, sid, "rate_limited")
    enq = AsyncMock()
    await _run_retry_cron(db_session, mock_redis, enq)
    enq.assert_not_awaited()
    job = await db_session.get(DownloadJob, jid)
    await db_session.refresh(job)
    assert (job.status, job.retry_count) == ("failed", 0)


async def test_retry_cron_still_retries_failed_jobs_of_unpaused_subscription(db_session, mock_redis):
    """Control for the paused-subscription test: the gate must not block normal retries."""
    sid = await _sub(db_session)
    await _job(db_session, sid, "failed", 1)
    enq = AsyncMock()
    await _run_retry_cron(db_session, mock_redis, enq)
    enq.assert_awaited_once()


async def _startup_with_real_sessions(redis, factory, enqueue):
    """Run worker.startup() with each AsyncSessionLocal() a fresh, properly closed test session."""
    from tests.test_worker_recovery import _startup_patches
    from worker import startup

    worker = MagicMock()
    worker.queue = AsyncMock()
    with (
        _startup_patches(redis, MagicMock(), enqueue),
        patch("core.database.AsyncSessionLocal", factory),
        # Postgres-only sweeps (pg_tables); their SQLite failure leaves the shared connection dirty (BE-T25).
        patch("worker._sweep_orphan_repair_archives", AsyncMock(return_value=0)),
        patch("worker._settle_orphan_downloading_galleries", AsyncMock(return_value=0)),
        patch("worker.import_recovery.requeue_orphaned_imports", AsyncMock(return_value={"requeued": 0})),
    ):
        await startup({"redis": redis, "worker": worker})


async def test_startup_auto_retry_strategy_keeps_paused_subscription_jobs_paused(
    db_session, db_session_factory, mock_redis
):
    """setting:recovery_paused=auto_retry must not revive jobs of a paused subscription."""
    from tests.test_worker_recovery import _make_redis

    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "paused", 1)
    await _mark_paused(db_session, sid, "manual")
    redis = _make_redis(strategy_running="auto_retry", strategy_paused="auto_retry")
    enqueue = AsyncMock()

    await _startup_with_real_sessions(redis, db_session_factory, enqueue)

    job = await db_session.get(DownloadJob, jid)
    await db_session.refresh(job)
    assert (job.status, job.retry_count) == ("paused", 0)
    assert all(call.args[0].id != jid for call in enqueue.await_args_list)


async def test_startup_auto_retry_strategy_still_retries_paused_job_of_unpaused_subscription(
    db_session, db_session_factory, mock_redis
):
    """Control: recovery policy keeps working for jobs whose subscription is not paused."""
    from tests.test_worker_recovery import _make_redis

    sid = await _sub(db_session)
    jid = await _job(db_session, sid, "paused", 1)
    redis = _make_redis(strategy_running="auto_retry", strategy_paused="auto_retry")
    enqueue = AsyncMock()

    await _startup_with_real_sessions(redis, db_session_factory, enqueue)

    job = await db_session.get(DownloadJob, jid)
    await db_session.refresh(job)
    assert job.status == "queued"
    assert any(call.args[0].id == jid for call in enqueue.await_args_list)
