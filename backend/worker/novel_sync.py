"""SAQ cron job: keep the novel working clone synced with the bare hub remote.

Fetch + fast-forward pull when clean; retry unpushed commits (hub recovery).
Never merges — a non-ff situation is left for a user edit to trigger the
locked-state path in services.novel_git.

STAB-003: worker may import services, never routers.
"""

from __future__ import annotations

import core.queue
from core.config import settings
from services import novel_git
from services.settings_store import get_toggle
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run, acquire_lock, release_lock

TASK_ID = "novel_git_sync"
DEFAULT_CRON = "*/15 * * * *"
_LOCK = "novel:git:lock"


async def novel_sync_job(ctx: dict, force: bool = False) -> None:
    # Master feature flag wins even over force: no novel = no git access.
    if not await get_toggle("setting:novel_enabled", settings.novel_enabled):
        logger.info("[novel-sync] skipped — novel feature disabled")
        return
    r = ctx["redis"]
    if not force and not await _cron_should_run(ctx, TASK_ID, DEFAULT_CRON):
        return
    token = await acquire_lock(r, _LOCK, ttl=60)
    if token is None:
        logger.info("[novel-sync] skipped — git lock held")
        return
    repo = settings.novel_repo_path
    pulled = False
    try:
        await novel_git.fetch(repo)
        st = await novel_git.status(repo)
        if st["locked"]:
            logger.info("[novel-sync] repo locked; skipping pull")
        elif st["clean"] and st["behind"] > 0:
            pulled = await novel_git.pull_ff(repo)
        if st["ahead"] > 0:
            await novel_git.push(repo)  # retry unpushed (hub was offline)
        await _cron_record(ctx, TASK_ID, "ok")
    except Exception as exc:  # noqa: BLE001 — cron job must never crash the worker
        logger.warning("[novel-sync] failed: %s", exc)
        await _cron_record(ctx, TASK_ID, "failed", str(exc))
    finally:
        await release_lock(r, _LOCK, token)
    if pulled:
        # New commits landed in the working tree — refresh the knowledge index.
        # Enqueue AFTER releasing the git lock: novel_index_job takes the same
        # lock and skips without retry when it is held. Best-effort — the daily
        # index cron self-heals if the queue hiccups.
        try:
            await core.queue.enqueue("novel_index_job", force=True)
        except Exception as exc:
            logger.warning("[novel-sync] failed to enqueue novel_index_job: %s", exc)
