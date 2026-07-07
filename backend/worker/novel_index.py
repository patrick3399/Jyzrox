"""SAQ job: rebuild the novel knowledge index from the working tree.

Daily cron reconcile + enqueue-after-write (router) + manual admin trigger. Full
rebuild each run — the corpus is ~8 MB, so incremental diffing is YAGNI. Shares
the git lock so it never reads a tree mid-mutation by the sync/commit path.
STAB-003: imports services only, never routers.
"""

from __future__ import annotations

from core.config import settings
from core.database import async_session
from services.novel_index import reindex_all
from services.settings_store import get_toggle
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run, acquire_lock, release_lock

TASK_ID = "novel_index"
DEFAULT_CRON = "0 4 * * *"
_LOCK = "novel:git:lock"


async def novel_index_job(ctx: dict, force: bool = False) -> None:
    # Master feature flag wins even over force: no novel = no index.
    if not await get_toggle("setting:novel_enabled", settings.novel_enabled):
        logger.info("[novel-index] skipped — novel feature disabled")
        return
    r = ctx["redis"]
    if not force and not await _cron_should_run(ctx, TASK_ID, DEFAULT_CRON):
        return
    token = await acquire_lock(r, _LOCK, ttl=120)
    if token is None:
        logger.info("[novel-index] skipped — git lock held")
        return
    try:
        async with async_session() as session:
            stats = await reindex_all(session, settings.novel_repo_path)
            await session.commit()
        logger.info("[novel-index] reindexed: %s", stats)
        await _cron_record(ctx, TASK_ID, "ok")
    except Exception as exc:  # noqa: BLE001 — cron job must never crash the worker
        logger.warning("[novel-index] failed: %s", exc)
        await _cron_record(ctx, TASK_ID, "failed", str(exc))
    finally:
        await release_lock(r, _LOCK, token)
