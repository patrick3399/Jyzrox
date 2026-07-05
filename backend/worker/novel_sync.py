"""SAQ cron job: keep the novel working clone synced with the 214 bare hub.

Fetch + fast-forward pull when clean; retry unpushed commits (214 recovery).
Never merges — a non-ff situation is left for a user edit to trigger the
locked-state path in services.novel_git.

STAB-003: worker may import services, never routers.
"""

from __future__ import annotations

from core.config import settings
from services import novel_git
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run, acquire_lock, release_lock

TASK_ID = "novel_git_sync"
DEFAULT_CRON = "*/15 * * * *"
_LOCK = "novel:git:lock"


async def novel_sync_job(ctx: dict, force: bool = False) -> None:
    r = ctx["redis"]
    if not force and not await _cron_should_run(ctx, TASK_ID, DEFAULT_CRON):
        return
    token = await acquire_lock(r, _LOCK, ttl=60)
    if token is None:
        logger.info("[novel-sync] skipped — git lock held")
        return
    repo = settings.novel_repo_path
    try:
        await novel_git.fetch(repo)
        st = await novel_git.status(repo)
        if st["locked"]:
            logger.info("[novel-sync] repo locked; skipping pull")
        elif st["clean"] and st["behind"] > 0:
            await novel_git.pull_ff(repo)
        if st["ahead"] > 0:
            await novel_git.push(repo)  # retry unpushed (214 was offline)
        await _cron_record(ctx, TASK_ID, "ok")
    except Exception as exc:  # noqa: BLE001 — cron job must never crash the worker
        logger.warning("[novel-sync] failed: %s", exc)
        await _cron_record(ctx, TASK_ID, "failed", str(exc))
    finally:
        await release_lock(r, _LOCK, token)
