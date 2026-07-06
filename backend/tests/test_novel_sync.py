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
