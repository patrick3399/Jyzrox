"""Tests for the novel_git_sync cron job (Task 7)."""

from unittest.mock import AsyncMock

from worker import novel_sync


def _ctx():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)  # acquire_lock succeeds
    r.eval = AsyncMock(return_value=1)  # release_lock
    return {"redis": r}


async def test_sync_job_pulls_when_behind_and_retries_push(monkeypatch):
    monkeypatch.setattr(novel_sync, "get_toggle", AsyncMock(return_value=True), raising=False)
    calls = []
    monkeypatch.setattr(novel_sync.novel_git, "fetch", AsyncMock(side_effect=lambda repo: calls.append("fetch")))
    monkeypatch.setattr(novel_sync.novel_git, "pull_ff", AsyncMock(side_effect=lambda repo: calls.append("pull")))
    monkeypatch.setattr(novel_sync.novel_git, "push", AsyncMock(side_effect=lambda repo: calls.append("push")))
    monkeypatch.setattr(
        novel_sync.novel_git,
        "status",
        AsyncMock(return_value={"head": "abc", "ahead": 1, "behind": 1, "clean": True, "locked": False}),
    )
    monkeypatch.setattr(novel_sync, "_cron_record", AsyncMock())

    await novel_sync.novel_sync_job(_ctx(), force=True)

    assert calls == ["fetch", "pull", "push"]


async def test_sync_job_skips_pull_when_locked(monkeypatch):
    monkeypatch.setattr(novel_sync, "get_toggle", AsyncMock(return_value=True), raising=False)
    calls = []
    monkeypatch.setattr(novel_sync.novel_git, "fetch", AsyncMock(side_effect=lambda repo: calls.append("fetch")))
    monkeypatch.setattr(novel_sync.novel_git, "pull_ff", AsyncMock(side_effect=lambda repo: calls.append("pull")))
    monkeypatch.setattr(novel_sync.novel_git, "push", AsyncMock(side_effect=lambda repo: calls.append("push")))
    monkeypatch.setattr(
        novel_sync.novel_git,
        "status",
        AsyncMock(return_value={"head": "abc", "ahead": 0, "behind": 2, "clean": True, "locked": True}),
    )
    monkeypatch.setattr(novel_sync, "_cron_record", AsyncMock())

    await novel_sync.novel_sync_job(_ctx(), force=True)

    assert calls == ["fetch"]  # locked → no pull, ahead=0 → no push


async def test_sync_job_records_failure_but_does_not_raise(monkeypatch):
    monkeypatch.setattr(novel_sync, "get_toggle", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(novel_sync.novel_git, "fetch", AsyncMock(side_effect=RuntimeError("214 down")))
    recorded = []
    monkeypatch.setattr(
        novel_sync,
        "_cron_record",
        AsyncMock(side_effect=lambda ctx, tid, status, error=None: recorded.append((status, error))),
    )

    await novel_sync.novel_sync_job(_ctx(), force=True)  # must not raise

    assert recorded and recorded[0][0] == "failed"


async def test_sync_job_skips_when_novel_feature_disabled_even_with_force(monkeypatch):
    """Master feature flag off → job returns immediately, no git access, even force=True."""
    monkeypatch.setattr(novel_sync, "get_toggle", AsyncMock(return_value=False), raising=False)
    fetch = AsyncMock()
    monkeypatch.setattr(novel_sync.novel_git, "fetch", fetch)

    await novel_sync.novel_sync_job(_ctx(), force=True)

    fetch.assert_not_called()


# ── Phase 1.6: a cron pull that lands new commits must refresh the index ────


def _order_mocks(monkeypatch, *, behind: int):
    """Wire fetch/status/pull/push + lock mocks that record call order."""
    import core.queue

    order = []
    monkeypatch.setattr(novel_sync, "get_toggle", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(novel_sync.novel_git, "fetch", AsyncMock())
    monkeypatch.setattr(
        novel_sync.novel_git,
        "status",
        AsyncMock(return_value={"head": "abc", "ahead": 0, "behind": behind, "clean": True, "locked": False}),
    )

    async def _pull(repo):
        order.append("pull")
        return True

    monkeypatch.setattr(novel_sync.novel_git, "pull_ff", _pull)
    monkeypatch.setattr(novel_sync.novel_git, "push", AsyncMock())
    monkeypatch.setattr(novel_sync, "_cron_record", AsyncMock())

    async def _release(r, key, token):
        order.append("release")
        return 1

    monkeypatch.setattr(novel_sync, "release_lock", _release)

    async def _enqueue(job_name, **kwargs):
        order.append(("enqueue", job_name, kwargs))

    monkeypatch.setattr(core.queue, "enqueue", _enqueue)
    return order


async def test_sync_job_pull_enqueues_novel_index_job_after_lock_release(monkeypatch):
    """New commits pulled by the cron must trigger a reindex — and only after
    the git lock is released, because novel_index_job takes the same lock and
    skips WITHOUT retry when it is held."""
    order = _order_mocks(monkeypatch, behind=2)

    await novel_sync.novel_sync_job(_ctx(), force=True)

    expected = ("enqueue", "novel_index_job", {"force": True})
    assert expected in order
    assert order.index("release") < order.index(expected)


async def test_sync_job_without_new_commits_does_not_enqueue_index_job(monkeypatch):
    order = _order_mocks(monkeypatch, behind=0)

    await novel_sync.novel_sync_job(_ctx(), force=True)

    assert "pull" not in order
    assert not any(isinstance(c, tuple) and c[0] == "enqueue" for c in order)


async def test_sync_job_index_enqueue_failure_does_not_raise(monkeypatch):
    """Cron jobs must never crash the worker — a queue hiccup after a good
    pull is logged, and the daily index cron self-heals."""
    import core.queue

    _order_mocks(monkeypatch, behind=2)
    monkeypatch.setattr(core.queue, "enqueue", AsyncMock(side_effect=RuntimeError("queue down")))

    await novel_sync.novel_sync_job(_ctx(), force=True)  # must not raise
