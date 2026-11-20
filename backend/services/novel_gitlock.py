"""Novel git lock, writability guard and reindex enqueue shared by the novel routers."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import HTTPException

import core.queue
from core.config import settings
from core.redis_client import get_redis
from services import novel_fs, novel_git
from worker.helpers import acquire_lock, release_lock, renew_lock

_GIT_LOCK = "novel:git:lock"
# Renewed while the operation runs, so the TTL only matters if the process dies.
_GIT_LOCK_TTL = 60
_GIT_LOCK_RENEW_INTERVAL = 20
logger = logging.getLogger(__name__)


async def _enqueue_reindex() -> None:
    """Refresh the knowledge index after a working-tree mutation.

    Best-effort: the git mutation already succeeded, so a queue outage must not
    fail the request — the daily index cron self-heals. Call this only AFTER
    the git lock is released: novel_index_job takes the same lock and skips
    without retry when it is held.
    """
    try:
        await core.queue.enqueue("novel_index_job", force=True)
    except Exception as exc:
        logger.warning("failed to enqueue novel_index_job after novel mutation: %s", exc)


def _repo() -> str:
    return settings.novel_repo_path


async def _with_git_lock(coro_factory):
    """Serialize every repo-mutating git op on the Redis lock `novel:git:lock`.

    The lock is renewed for as long as the operation is still running.
    ``commit_and_push`` can chain commit + push + fetch + rebase + push, each
    with its own 30s subprocess timeout, so a fixed 60s TTL could expire while
    the work was still in progress and let a second request into the same repo.
    ``release_lock`` is token-checked and so would never delete the new holder's
    lock, but nothing prevented the two operations from overlapping.

    A renewal that returns False means the lock is gone or has changed hands.
    That is logged rather than raised: the git work is already underway and
    aborting mid-rebase would leave a worse state than finishing.
    """
    r = get_redis()
    token = await acquire_lock(r, _GIT_LOCK, ttl=_GIT_LOCK_TTL)
    if token is None:
        raise HTTPException(status_code=409, detail="git busy, retry")

    async def _keep_held() -> None:
        while True:
            await asyncio.sleep(_GIT_LOCK_RENEW_INTERVAL)
            if not await renew_lock(r, _GIT_LOCK, token, _GIT_LOCK_TTL):
                logger.error(
                    "novel git lock lost while the operation was still running; another writer may now be in the repo"
                )
                return

    heartbeat = asyncio.create_task(_keep_held())
    try:
        return await coro_factory()
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await release_lock(r, _GIT_LOCK, token)


async def _assert_writable(repo: str, path: str, base_sha: str | None) -> None:
    """Pre-write guard for every mutating endpoint. MUST run under the git lock:
    checking before taking it is a lost-update TOCTOU (a commit could land
    between the check and the write).

    `base_sha=None` means "create": a brand-new file has no base revision to be
    stale against, so its only invariant is that the path is free.
    """
    st = await novel_git.status(repo)
    if st["locked"]:
        raise HTTPException(status_code=409, detail="repo locked; resolve on desktop")
    if base_sha is None:
        if novel_fs.file_exists(repo, path):
            raise HTTPException(status_code=409, detail={"error": "file exists"})
        return
    if st["head"] != base_sha:
        try:
            current = novel_fs.read_file(repo, path)
        except FileNotFoundError:
            current = ""
        raise HTTPException(
            status_code=409,
            detail={"error": "stale base_sha", "current": current, "current_sha": st["head"]},
        )
